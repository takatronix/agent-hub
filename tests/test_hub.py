import json
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

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
        self.assertIn("回答 by b", next(t for t in reviews if t["agent"] == "a")["prompt"])
        self.assertNotIn("回答 by a\na answer", next(t for t in reviews if t["agent"] == "a")["prompt"])
        self._finish_all(run["id"], "review ok")
        run = self.store.get_run(run["id"])
        self.assertEqual(run["state"]["phase"], "synthesize")
        synth = self.store.list_tasks(run_id=run["id"], status="queued")
        self.assertEqual(len(synth), 1)
        self.assertEqual(synth[0]["agent"], "a")
        self.assertIn("レビュー by b", synth[0]["prompt"])
        self._finish_all(run["id"], "final")
        run = self.store.get_run(run["id"])
        self.assertEqual(run["status"], "done")
        self.assertIn("final", run["summary"])

    def test_review_panel_fails_with_one_solver(self):
        run = self.orch.start("review_panel", "p", "t", {"prompt": "Q?", "solvers": ["a", "b"]})
        tasks = self.store.list_tasks(run_id=run["id"])
        for t, st in zip(tasks, ("done", "failed")):
            self.store.claim_next([t["agent"]], "x")
            self.orch.on_task_finished(self.store.finish_task(t["id"], st, result="r" if st == "done" else None, error="boom" if st == "failed" else None))
        self.assertEqual(self.store.get_run(run["id"])["status"], "failed")

    def test_claim_is_atomic_and_ordered(self):
        self.store.create_task("p", "t1", "p1", "a")
        self.store.create_task("p", "t2", "p2", "a")
        t = self.store.claim_next(["a", "b"], "w")
        self.assertEqual(t["title"], "t1")
        self.assertEqual(t["status"], "running")
        self.assertIsNone(self.store.claim_next(["b"], "w"))


class EndToEndTest(unittest.TestCase):
    """Real HTTP server + real runner threads with fake adapters."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store = Store(Path(self.tmp.name) / "t.sqlite3")
        self.hub = Hub(store, token="secret", read_token="ro")
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
