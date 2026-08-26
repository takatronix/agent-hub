import tempfile
import unittest
from pathlib import Path

from agent_hub.recipes import Orchestrator
from agent_hub.store import Store


class BackendFixesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.sqlite3")
        self.orch = Orchestrator(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def _claimed_task(self, claimed_by="claude-a@host1"):
        t = self.store.create_task("p", "title", "prompt", "claude-a")
        self.store.claim_next(["claude-a"], claimed_by)
        return self.store.get_task(t["id"])

    def test_finish_task_ignores_mismatched_claimed_by(self):
        t = self._claimed_task("claude-a@host1")
        # A stale/reaped runner (different claimed_by) must not overwrite the result.
        out = self.store.finish_task(t["id"], "done", result="stolen", claimed_by="claude-a@host2")
        self.assertEqual(out["status"], "running")
        self.assertIsNone(out["result"])
        cur = self.store.get_task(t["id"])
        self.assertEqual(cur["status"], "running")
        self.assertIsNone(cur["result"])

    def test_finish_task_accepts_matching_claimed_by(self):
        t = self._claimed_task("claude-a@host1")
        out = self.store.finish_task(t["id"], "done", result="ok", claimed_by="claude-a@host1")
        self.assertEqual(out["status"], "done")
        self.assertEqual(out["result"], "ok")

    def test_finish_task_without_claimed_by_is_backward_compatible(self):
        t = self._claimed_task("claude-a@host1")
        out = self.store.finish_task(t["id"], "done", result="ok")
        self.assertEqual(out["status"], "done")
        self.assertEqual(out["result"], "ok")

    def test_finish_task_claimed_by_on_unclaimed_task(self):
        # task["claimed_by"] is None -> guard does not block (nothing to protect yet).
        t = self.store.create_task("p", "title", "prompt", "claude-a")
        out = self.store.finish_task(t["id"], "done", result="ok", claimed_by="whoever@host")
        self.assertEqual(out["status"], "done")
        self.assertEqual(out["result"], "ok")

    def test_finish_after_cancel_stays_cancelled(self):
        run = self.orch.start("single", "p", "t", {"prompt": "Q?", "agent": "claude-a"})
        task = self.store.list_tasks(run_id=run["id"])[0]
        self.store.claim_next(["claude-a"], "claude-a@host1")
        self.orch.cancel(run["id"])
        # A late finish (even with the correct claimed_by) must not resurrect the task.
        out = self.store.finish_task(task["id"], "done", result="too late", claimed_by="claude-a@host1")
        self.assertEqual(out["status"], "cancelled")
        self.assertIsNone(out["result"])
        self.assertEqual(self.store.get_run(run["id"])["status"], "cancelled")

    def test_cancel_after_finish_does_not_spawn_next_phase(self):
        # review_panel: cancel between phases must not let a finishing task advance the phase.
        run = self.orch.start("review_panel", "p", "t", {"prompt": "Q?", "solvers": ["a", "b"]})
        solves = self.store.list_tasks(run_id=run["id"], status="queued")
        self.assertEqual(len(solves), 2)
        for t in solves:
            self.store.claim_next([t["agent"]], f"{t['agent']}@h")
        self.orch.cancel(run["id"])
        # Finishing tasks now (as a runner would) must not create review tasks.
        for t in solves:
            done = self.store.finish_task(t["id"], "done", result=f"{t['agent']} ans\n## 結論\nok",
                                          claimed_by=f"{t['agent']}@h")
            self.assertEqual(done["status"], "cancelled")
            self.orch.on_task_finished(done)
        self.assertEqual(self.store.get_run(run["id"])["status"], "cancelled")
        self.assertEqual([t["step"] for t in self.store.list_tasks(run_id=run["id"])], ["solve", "solve"])

    def test_finish_task_is_idempotent_on_terminal_state(self):
        # A second finish (double delivery / same runner re-posting) must not overwrite a settled task.
        t = self._claimed_task("claude-a@host1")
        self.store.finish_task(t["id"], "done", result="first", claimed_by="claude-a@host1")
        out = self.store.finish_task(t["id"], "failed", error="second", claimed_by="claude-a@host1")
        self.assertEqual(out["status"], "done")
        self.assertEqual(out["result"], "first")
        self.assertIsNone(out["error"])


if __name__ == "__main__":
    unittest.main()
