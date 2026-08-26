import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

from agent_hub.server import Hub, make_server
from agent_hub.store import Store


class ServerFixesTest(unittest.TestCase):
    """HTTP-level checks for input validation (400) and keep-alive drain."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store = Store(Path(self.tmp.name) / "t.sqlite3")
        self.hub = Hub(store, token=None, read_token=None, reaper=False)
        self.srv = make_server("127.0.0.1", 0, self.hub)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.tmp.cleanup()

    def _post(self, conn, path, body):
        raw = json.dumps(body).encode("utf-8")
        conn.request("POST", path, raw, {"Content-Type": "application/json", "Content-Length": str(len(raw))})
        return conn.getresponse()

    def test_missing_keys_return_400(self):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        for path, body in (("/api/tasks", {"agent": "x"}), ("/api/tasks", {"prompt": "hi"}),
                           ("/api/agents/heartbeat", {}), ("/api/projects", {})):
            r = self._post(conn, path, body)
            self.assertEqual(r.status, 400, (path, body))
            self.assertIn("missing", json.loads(r.read())["error"])
        conn.close()

    def test_tasks_ok_with_keys(self):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        r = self._post(conn, "/api/tasks", {"prompt": "hi", "agent": "fake-a"})
        self.assertEqual(r.status, 201)
        self.assertIn("task", json.loads(r.read()))
        conn.close()

    def test_keepalive_after_empty_body_cancel(self):
        """A body-less POST (cancel) must not leave bytes on the socket that corrupt the next request."""
        run = self.hub.orch.start("single", "default", "t", {"prompt": "hi", "agent": "fake-a"}, "")
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        # cancel with NO Content-Length / empty body over a keep-alive connection
        conn.request("POST", f"/api/runs/{run['id']}/cancel")
        r1 = conn.getresponse()
        self.assertEqual(r1.status, 200)
        r1.read()
        self.assertEqual(r1.getheader("Connection", "keep-alive").lower(), "keep-alive")
        # reuse the SAME connection for a follow-up GET — must succeed cleanly
        conn.request("GET", "/api/health")
        r2 = conn.getresponse()
        self.assertEqual(r2.status, 200)
        self.assertTrue(json.loads(r2.read())["ok"])
        conn.close()

    def test_keepalive_after_body_post_drained(self):
        """A POST route that never calls _body() must still drain the request body for the next request."""
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        # /api/agents/<name>/delete ignores the body entirely; send one anyway
        raw = json.dumps({"junk": "x" * 500}).encode("utf-8")
        conn.request("POST", "/api/agents/ghost/delete", raw,
                     {"Content-Type": "application/json", "Content-Length": str(len(raw))})
        r1 = conn.getresponse()
        self.assertEqual(r1.status, 200)
        r1.read()
        conn.request("GET", "/api/health")
        r2 = conn.getresponse()
        self.assertEqual(r2.status, 200)
        self.assertTrue(json.loads(r2.read())["ok"])
        conn.close()


if __name__ == "__main__":
    unittest.main()
