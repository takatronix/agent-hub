import json
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

from agent_hub import league
from agent_hub.client import HubClient
from agent_hub.recipes import Orchestrator
from agent_hub.runner import AgentWorker
from agent_hub.server import Hub, make_server
from agent_hub.store import Store


class StoreRecipeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.sqlite3")
        self.orch = Orchestrator(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def _finish_all(self, run_id, text="answer\n## 結論\nok"):
        for t in self.store.list_tasks(run_id=run_id, status="queued"):
            self.store.claim_next([t["agent"]], "test")
            done = self.store.finish_task(t["id"], "done", result=f"{t['agent']} {text}")
            self.orch.on_task_finished(done)

    def test_review_panel_flow(self):
        run = self.orch.start("review_panel", "p", "t", {"prompt": "Q?", "solvers": ["a", "b", "c"]})
        self.assertEqual(run["state"]["phase"], "solve")
        self.assertEqual(len(self.store.list_tasks(run_id=run["id"])), 3)
        self._finish_all(run["id"])
        run = self.store.get_run(run["id"])
        self.assertEqual(run["state"]["phase"], "review")
        reviews = self.store.list_tasks(run_id=run["id"], status="queued")
        self.assertEqual(sorted(t["agent"] for t in reviews), ["a", "b", "c"])
        pa = next(t for t in reviews if t["agent"] == "a")["prompt"]
        self.assertIn("回答 B", pa)
        self.assertNotIn("回答 A\n", pa)  # own answer is not among the review targets
        self.assertNotIn('"A": <1-10>', pa)
        self.assertIn('"B": <1-10>', pa)
        for t in reviews:
            self.store.claim_next([t["agent"]], "test")
            others = [k for k, v in run["state"]["aliases"].items() if v != t["agent"]]
            scores = ", ".join(f'"{k}": {7 if k == "B" else 4}' for k in others)
            done = self.store.finish_task(t["id"], "done", result=f'review\n```json\n{{"scores": {{{scores}}}, "best": "B"}}\n```')
            self.orch.on_task_finished(done)
        run = self.store.get_run(run["id"])
        self.assertEqual(run["state"]["phase"], "synthesize")
        synth = self.store.list_tasks(run_id=run["id"], status="queued")
        self.assertEqual(len(synth), 1)
        self.assertEqual(synth[0]["agent"], "a")
        self.assertIn("回答 B", synth[0]["prompt"])
        self.assertIn("レビュー 1", synth[0]["prompt"])
        self.assertNotIn("レビュー by", synth[0]["prompt"])
        self._finish_all(run["id"], 'final\n```json\n{"adopted": ["B"]}\n```')
        run = self.store.get_run(run["id"])
        self.assertEqual(run["status"], "done")
        self.assertIn("final", run["summary"])
        res = run["state"]["results"]
        self.assertEqual(res["b"]["avg"], 7.0)
        self.assertEqual(res["b"]["best"], 2)
        self.assertTrue(res["b"]["adopted"])
        self.assertEqual(res["a"]["avg"], 4.0)
        board = league.leaderboard([run])
        self.assertEqual(board["b"]["all"]["adopted"], 1)
        self.assertEqual(board["b"][run["state"]["category"]]["best"], 2)
        rec = league.recommend(board, run["state"]["category"], [{"name": n, "kind": "claude" if n == "a" else "codex"} for n in "abc"], 2)
        self.assertEqual(rec["solvers"][0], "b")

    def test_review_panel_fails_with_one_solver(self):
        run = self.orch.start("review_panel", "p", "t", {"prompt": "Q?", "solvers": ["a", "b"]})
        tasks = self.store.list_tasks(run_id=run["id"])
        for t, st in zip(tasks, ("done", "failed")):
            self.store.claim_next([t["agent"]], "x")
            self.orch.on_task_finished(self.store.finish_task(t["id"], st, result="r" if st == "done" else None, error="boom" if st == "failed" else None))
        self.assertEqual(self.store.get_run(run["id"])["status"], "failed")

    def test_cancel_stops_running_tasks(self):
        run = self.orch.start("parallel", "p", "t", {"prompt": "Q", "agents": ["a", "b"]})
        self.store.claim_next(["a"], "a@x")
        self.orch.cancel(run["id"])
        self.assertEqual({t["status"] for t in self.store.list_tasks(run_id=run["id"])}, {"cancelled"})
        t = self.store.list_tasks(run_id=run["id"])[0]
        self.assertEqual(self.store.finish_task(t["id"], "done", result="late")["status"], "cancelled")

    def test_claim_is_atomic_and_ordered(self):
        self.store.create_task("p", "t1", "p1", "a")
        self.store.create_task("p", "t2", "p2", "a")
        t = self.store.claim_next(["a", "b"], "w")
        self.assertEqual(t["title"], "t1")
        self.assertEqual(t["status"], "running")
        self.assertIsNone(self.store.claim_next(["b"], "w"))


class LeagueParseTest(unittest.TestCase):
    def test_parse_scores_and_category(self):
        self.assertEqual(league.parse_scores('x ```json\n{"scores": {"a": 8, "C": "6"}, "best": "c"}\n```')["best"], "C")
        self.assertEqual(league.parse_scores('{"scores": {"B": 11}}')["scores"], {"B": 10.0})
        self.assertIsNone(league.parse_scores("no json here"))
        self.assertEqual(league.parse_category("カテゴリ: robotics\n..."), "robotics")
        self.assertEqual(league.parse_adopted('```json {"adopted": "b"} ```'), ["B"])
        self.assertEqual(league.guess_category("ROS の launch が落ちる"), "robotics")


class ReaperTest(unittest.TestCase):
    def test_lost_task_is_requeued_then_failed(self):
        tmp = tempfile.TemporaryDirectory()
        store = Store(Path(tmp.name) / "t.sqlite3")
        hub = Hub(store, None, None, reaper=False)
        store.heartbeat("a", "fake", status="idle")
        t = store.create_task("p", "t", "prompt", "a")
        store.claim_next(["a"], "a@x")
        # not old enough yet
        self.assertEqual(hub.reap_lost_tasks(agent_grace=120), [])
        self.assertEqual(hub.reap_lost_tasks(agent_grace=0), [t["id"]])
        self.assertEqual(store.get_task(t["id"])["status"], "queued")
        store.claim_next(["a"], "a@x")
        self.assertEqual(hub.reap_lost_tasks(agent_grace=0), [t["id"]])
        self.assertEqual(store.get_task(t["id"])["status"], "failed")
        tmp.cleanup()


class EndToEndTest(unittest.TestCase):
    """Real HTTP server + real runner threads with fake adapters."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store = Store(Path(self.tmp.name) / "t.sqlite3")
        self.hub = Hub(store, token="secret", read_token="ro", reaper=False)
        self.srv = make_server("127.0.0.1", 0, self.hub)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.client = HubClient(f"http://127.0.0.1:{self.port}", "secret", timeout=40)
        self.workers = [AgentWorker(self.client, "testhost", {"name": n, "kind": "fake", "delay": 0.01}, 0.05, None)
                        for n in ("fake-a", "fake-b", "fake-c")]
        for w in self.workers:
            w.start()

    def tearDown(self):
        for w in self.workers:
            w.stop.set()
        self.srv.shutdown()
        self.tmp.cleanup()

    def test_auth(self):
        with self.assertRaises(RuntimeError):
            HubClient(f"http://127.0.0.1:{self.port}", "wrong").get("/api/runs")
        self.assertIn("runs", HubClient(f"http://127.0.0.1:{self.port}", "ro").get("/api/runs"))
        with self.assertRaises(RuntimeError):
            HubClient(f"http://127.0.0.1:{self.port}", "ro").post("/api/projects", {"name": "x"})

    def test_panel_end_to_end(self):
        run = self.client.post("/api/runs", {"recipe": "review_panel", "project": "demo", "title": "demo",
                                              "spec": {"prompt": "What is 6*7?", "solvers": ["fake-a", "fake-b", "fake-c"]}})["run"]
        deadline = time.time() + 30
        while time.time() < deadline:
            run = self.client.get(f"/api/runs/{run['id']}")["run"]
            if run["status"] != "running":
                break
            time.sleep(0.2)
        self.assertEqual(run["status"], "done", run)
        steps = sorted((t["step"], t["agent"]) for t in run["tasks"])
        self.assertEqual(len([s for s in steps if s[0] == "solve"]), 3)
        self.assertEqual(len([s for s in steps if s[0] == "review"]), 3)
        self.assertEqual([s for s in steps if s[0] == "synthesize"], [("synthesize", "fake-a")])
        self.assertIn("最終回答", run["summary"])
        msgs = self.client.get(f"/api/runs/{run['id']}/messages")["messages"]
        roles = {m["role"] for m in msgs}
        self.assertTrue({"system", "tool_use", "tool_result", "result"} <= roles)
        self.assertTrue(all(m["data"]["host"] if False else True for m in msgs))
        agents = self.client.get("/api/agents")["agents"]
        self.assertEqual(sorted(a["name"] for a in agents), ["fake-a", "fake-b", "fake-c"])
        self.assertTrue(all(a["online"] for a in agents))
        html = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/runs/{run['id']}?token=ro").read().decode()
        self.assertIn("agent-hub", html)

    def test_sse_stream(self):
        got = []
        def listen():
            req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/stream", headers={"Authorization": "Bearer ro"})
            with urllib.request.urlopen(req, timeout=20) as r:
                for line in r:
                    line = line.decode()
                    if line.startswith("data:"):
                        got.append(json.loads(line[5:]))
                        if any(g["event"] == "run" and g["run"]["status"] == "done" for g in got):
                            return
        th = threading.Thread(target=listen, daemon=True)
        th.start()
        time.sleep(0.3)
        self.client.post("/api/runs", {"recipe": "single", "title": "s", "spec": {"prompt": "hi", "agent": "fake-a"}})
        th.join(20)
        self.assertTrue(any(g["event"] == "message" for g in got))
        self.assertTrue(any(g["event"] == "run" and g["run"]["status"] == "done" for g in got))


if __name__ == "__main__":
    unittest.main()
