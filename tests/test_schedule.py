import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from agent_hub.client import HubClient
from agent_hub.server import Hub, make_server
from agent_hub.store import Store, _advance_next, _iso_plus
from agent_hub.util import now_iso


class ScheduleStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_and_claim_due_advances_next_at(self):
        sch = self.store.create_schedule("p", "nightly", "single", 3600,
                                         spec={"prompt": "hi", "agent": "a"}, notify="on_report")
        self.assertIsInstance(sch["spec"], dict)  # spec is parsed, not a string
        self.assertEqual(sch["spec"]["prompt"], "hi")
        self.assertEqual(sch["enabled"], 1)
        # not due yet (next_at is now+3600)
        self.assertEqual(self.store.claim_due_schedules(now_iso()), [])
        # force it due by asking with a far-future 'now'
        future = _iso_plus(now_iso(), 4000)
        due = self.store.claim_due_schedules(future)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["id"], sch["id"])
        self.assertIsInstance(due[0]["spec"], dict)
        # next_at has advanced strictly past `future`
        after = self.store.get_schedule(sch["id"])
        self.assertGreater(after["next_at"], future)
        # claiming again at the same 'now' returns nothing (already advanced)
        self.assertEqual(self.store.claim_due_schedules(future), [])

    def test_coalesce_skips_accumulated_intervals(self):
        sch = self.store.create_schedule("p", "s", "single", 60, spec={})
        # ~10.5 intervals worth of lag collapses into a single hop past `now`
        far = _iso_plus(sch["next_at"], 630)
        due = self.store.claim_due_schedules(far)
        self.assertEqual(len(due), 1)
        after = self.store.get_schedule(sch["id"])
        # next_at lands in the single interval just past `far`, not 10 separate fires
        self.assertGreater(after["next_at"], far)
        self.assertLessEqual(after["next_at"], _iso_plus(far, 60))

    def test_advance_next_helper(self):
        base = "2026-01-01T00:00:00.000Z"
        # next_at in the future is unchanged-ish (still > now, coalesce not triggered)
        self.assertEqual(_advance_next(base, 60, "2025-12-31T23:59:00.000Z"), base)
        nxt = _advance_next(base, 60, "2026-01-01T00:04:30.000Z")
        self.assertGreater(nxt, "2026-01-01T00:04:30.000Z")
        self.assertLessEqual(nxt, "2026-01-01T00:05:00.000Z")

    def test_toggle_and_delete(self):
        sch = self.store.create_schedule("p", "s", "single", 60)
        off = self.store.toggle_schedule(sch["id"])
        self.assertEqual(off["enabled"], 0)
        # disabled schedules are never claimed
        self.assertEqual(self.store.claim_due_schedules(_iso_plus(now_iso(), 999)), [])
        on = self.store.toggle_schedule(sch["id"])
        self.assertEqual(on["enabled"], 1)
        self.assertTrue(self.store.delete_schedule(sch["id"]))
        self.assertIsNone(self.store.get_schedule(sch["id"]))
        self.assertFalse(self.store.delete_schedule(sch["id"]))

    def test_set_last_run(self):
        sch = self.store.create_schedule("p", "s", "single", 60)
        self.store.set_schedule_last_run(sch["id"], "run_xyz")
        self.assertEqual(self.store.get_schedule(sch["id"])["last_run_id"], "run_xyz")

    def test_prune_old_removes_only_finished_messages(self):
        # finished, old run: messages get pruned, run + tasks remain
        old = self.store.create_run("p", "old", "single", {})
        self.store.create_task("p", "t", "prompt", "a", run_id=old["id"])
        self.store.add_message(actor="hub", role="system", run_id=old["id"], content="old msg")
        self.store.update_run(old["id"], status="done", summary="done")
        # backdate updated_at beyond the retention window
        with self.store.lock:
            self.store._conn.execute("UPDATE runs SET updated_at=? WHERE id=?",
                                     ("2000-01-01T00:00:00.000Z", old["id"]))
        # a running run keeps its messages
        live = self.store.create_run("p", "live", "single", {})
        self.store.add_message(actor="hub", role="system", run_id=live["id"], content="live msg")

        n = self.store.prune_old(days=14)
        self.assertGreaterEqual(n, 1)
        self.assertEqual(self.store.list_messages(run_id=old["id"]), [])
        self.assertIsNotNone(self.store.get_run(old["id"]))  # run body kept
        self.assertEqual(len(self.store.list_tasks(run_id=old["id"])), 1)  # tasks kept
        self.assertEqual(len(self.store.list_messages(run_id=live["id"])), 1)  # live untouched


class ScheduleHttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store = Store(Path(self.tmp.name) / "t.sqlite3")
        # scheduler=False so nothing auto-fires; we drive the lifecycle by hand
        self.hub = Hub(store, token="secret", read_token="ro", reaper=False, scheduler=False)
        self.srv = make_server("127.0.0.1", 0, self.hub)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.client = HubClient(f"http://127.0.0.1:{self.port}", "secret", timeout=20)

    def tearDown(self):
        self.srv.shutdown()
        self.tmp.cleanup()

    def _status(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method)
        req.add_header("Authorization", "Bearer secret")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read())
            finally:
                e.close()

    def test_lifecycle(self):
        # missing required key -> 400
        code, body = self._status("POST", "/api/schedules", {"title": "x", "recipe": "single"})
        self.assertEqual(code, 400)
        self.assertIn("interval_sec", body["error"])

        # create -> 201, spec parsed as an object
        code, body = self._status("POST", "/api/schedules",
                                  {"title": "daily", "recipe": "single", "interval_sec": 3600,
                                   "spec": {"prompt": "hi", "agent": "fake-a"}, "notify": "always"})
        self.assertEqual(code, 201)
        sch = body["schedule"]
        self.assertIsInstance(sch["spec"], dict)
        self.assertEqual(sch["notify"], "always")
        sid = sch["id"]

        # list
        listed = self.client.get("/api/schedules")["schedules"]
        self.assertEqual([s["id"] for s in listed], [sid])
        self.assertIsInstance(listed[0]["spec"], dict)

        # run_now -> 201, creates a run and stamps last_run_id
        code, body = self._status("POST", f"/api/schedules/{sid}/run_now")
        self.assertEqual(code, 201)
        run = body["run"]
        self.assertEqual(run["spec"]["schedule_id"], sid)
        self.assertEqual(run["spec"]["notify"], "always")
        self.assertEqual(self.hub.store.get_schedule(sid)["last_run_id"], run["id"])
        # run_now must not touch next_at
        self.assertEqual(self.hub.store.get_schedule(sid)["next_at"], sch["next_at"])

        # toggle flips enabled
        _, body = self._status("POST", f"/api/schedules/{sid}/toggle")
        self.assertEqual(body["schedule"]["enabled"], 0)

        # delete
        _, body = self._status("POST", f"/api/schedules/{sid}/delete")
        self.assertTrue(body["deleted"])
        self.assertEqual(self.client.get("/api/schedules")["schedules"], [])

    def test_create_validates_input(self):
        # unknown recipe / non-positive interval / non-object spec / bad notify -> 400 (not stored)
        for bad in ({"title": "x", "recipe": "nope", "interval_sec": 60},
                    {"title": "x", "recipe": "single", "interval_sec": 0},
                    {"title": "x", "recipe": "single", "interval_sec": -5},
                    {"title": "x", "recipe": "single", "interval_sec": 60, "spec": "notadict"},
                    {"title": "x", "recipe": "single", "interval_sec": 60, "notify": "whenever"}):
            code, _ = self._status("POST", "/api/schedules", bad)
            self.assertEqual(code, 400, bad)
        self.assertEqual(self.client.get("/api/schedules")["schedules"], [])

    def test_one_bad_schedule_does_not_skip_the_rest(self):
        # A schedule whose recipe is unknown must not prevent a sibling due schedule from running.
        st = self.hub.store
        past = "2000-01-01T00:00:00.000Z"
        bad = st.create_schedule("p", "bad", "single", 3600, spec={"prompt": "x", "agent": "fake-a"})
        good = st.create_schedule("p", "good", "single", 3600, spec={"prompt": "y", "agent": "fake-a"})
        # force both due and corrupt the first one's recipe directly in the DB
        with st.lock:
            st._conn.execute("UPDATE schedules SET next_at=?", (past,))
            st._conn.execute("UPDATE schedules SET recipe='bogus' WHERE id=?", (bad["id"],))
        self.hub._tick_schedules()
        self.assertIsNone(st.get_schedule(bad["id"])["last_run_id"])       # bad one failed
        self.assertIsNotNone(st.get_schedule(good["id"])["last_run_id"])   # good one still ran


if __name__ == "__main__":
    unittest.main()
