import time
import unittest
import urllib.request

from agent_hub import notify
from agent_hub.notify import Notifier


class NotifyTest(unittest.TestCase):
    def test_no_op_without_ntfy_url(self):
        n = Notifier(public_url="http://hub.local", ntfy_url=None)
        # emit must not raise and must not attempt any HTTP call
        n.emit({"id": "run_1", "status": "done", "title": "t", "summary": "s"})
        n.emit({"id": "run_2", "status": "failed", "title": "t", "summary": "s"})

    def test_posts_built_body(self):
        captured = {}

        class FakeResp:
            def close(self):
                pass

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["data"] = req.data
            captured["headers"] = {k: v for k, v in req.header_items()}
            return FakeResp()

        orig = notify.urllib.request.urlopen
        notify.urllib.request.urlopen = fake_urlopen
        try:
            n = Notifier(public_url="http://hub.local/", ntfy_url="https://ntfy.sh/mytopic")
            n.emit({"id": "run_abc", "status": "done", "title": "Nightly build",
                    "summary": "everything green " * 40})
            for _ in range(100):
                if captured:
                    break
                time.sleep(0.02)
        finally:
            notify.urllib.request.urlopen = orig

        self.assertEqual(captured["url"], "https://ntfy.sh/mytopic")
        self.assertEqual(captured["method"], "POST")
        # body carries the title (first line) + summary, so a non-latin title still notifies
        body = captured["data"].decode("utf-8")
        self.assertTrue(body.startswith("Nightly build\neverything green"))
        headers = {k.lower(): v for k, v in captured["headers"].items()}
        self.assertEqual(headers["title"], "Nightly build")  # ascii title also set as header
        self.assertEqual(headers["tags"], "white_check_mark")
        self.assertEqual(headers["click"], "http://hub.local/runs/run_abc")

    def test_japanese_title_goes_in_body_not_header(self):
        """Regression: a Japanese title in the latin-1 Title header used to raise
        UnicodeEncodeError and silently drop every notification in a Japanese UI."""
        captured = {}

        class FakeResp:
            def close(self):
                pass

        def fake_urlopen(req, timeout=None):
            captured["data"] = req.data
            captured["headers"] = {k.lower(): v for k, v in req.header_items()}
            return FakeResp()

        orig = notify.urllib.request.urlopen
        notify.urllib.request.urlopen = fake_urlopen
        try:
            n = Notifier(public_url="", ntfy_url="https://ntfy.sh/t")
            n.emit({"id": "r1", "status": "done", "title": "メール整理", "summary": "要対応3件"})
            for _ in range(100):
                if captured:
                    break
                time.sleep(0.02)
        finally:
            notify.urllib.request.urlopen = orig

        # must have sent without error, no latin-1-incompatible Title header
        self.assertNotIn("title", captured["headers"])
        self.assertIn("メール整理", captured["data"].decode("utf-8"))

    def test_failed_tag_and_fallback_body(self):
        captured = {}

        class FakeResp:
            def close(self):
                pass

        def fake_urlopen(req, timeout=None):
            captured["data"] = req.data
            captured["headers"] = {k.lower(): v for k, v in req.header_items()}
            return FakeResp()

        orig = notify.urllib.request.urlopen
        notify.urllib.request.urlopen = fake_urlopen
        try:
            n = Notifier(public_url="", ntfy_url="https://ntfy.sh/t")
            n.emit({"id": "r1", "status": "failed", "title": "job", "summary": ""})
            for _ in range(100):
                if captured:
                    break
                time.sleep(0.02)
        finally:
            notify.urllib.request.urlopen = orig

        self.assertEqual(captured["headers"]["tags"], "x")
        self.assertEqual(captured["data"], b"job")  # no summary -> body falls back to the title
        self.assertNotIn("click", captured["headers"])  # no public_url -> no Click


if __name__ == "__main__":
    unittest.main()
