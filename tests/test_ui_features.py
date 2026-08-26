"""String-level checks that the three UI features are present in INDEX_HTML
and that the important existing markers were not broken."""
import unittest

from agent_hub import ui


class TestUiFeatures(unittest.TestCase):
    def setUp(self):
        self.html = ui.INDEX_HTML

    # --- existing markers must survive ---
    def test_existing_markers_intact(self):
        for marker in ("function showRun", "function renderBody", "function showHome",
                       "function renderRuns", "function colHead", "function md(",
                       "EventSource", "function connect"):
            self.assertIn(marker, self.html, marker)

    # --- A. scheduled missions ---
    def test_schedule_toggle_and_interval(self):
        self.assertIn("定期実行", self.html)
        self.assertIn('id="schedon"', self.html)
        self.assertIn('id="interval"', self.html)
        # interval options incl. daily (86400)
        for v in ("1800", "3600", "21600", "86400"):
            self.assertIn(v, self.html)

    def test_schedules_api_wired(self):
        self.assertIn("/api/schedules", self.html)
        self.assertIn("interval_sec", self.html)
        self.assertIn("function renderSchedules", self.html)
        self.assertIn("/toggle", self.html)
        self.assertIn("/run_now", self.html)
        self.assertIn("/delete", self.html)
        self.assertIn("next_at", self.html)
        self.assertIn("last_run_id", self.html)

    def test_schedules_card_present(self):
        self.assertIn('id="schedules"', self.html)
        self.assertIn("定期ミッション", self.html)

    def test_jesc_escaper_present(self):
        self.assertIn("jesc", self.html)

    # --- B. notification toggle ---
    def test_notification_toggle(self):
        self.assertIn("Notification", self.html)
        self.assertIn("requestPermission", self.html)
        self.assertIn('id="bell"', self.html)
        self.assertIn("function notifyRun", self.html)
        # localStorage-backed like the theme toggle
        self.assertIn("localStorage.setItem('notify'", self.html)

    # --- C. agent activity line ---
    def test_activity_function(self):
        self.assertIn("function activityOf", self.html)
        # verb dictionary icons
        for icon in ("📖", "✏", "📝", "⚙", "🔍", "🤝", "🌐", "🔧", "🤔"):
            self.assertIn(icon, self.html)
        # inputs it inspects
        self.assertIn("file_path", self.html)
        self.assertIn("command", self.html)
        self.assertIn("pattern", self.html)
        self.assertIn("query", self.html)

    def test_activity_tracked_and_rendered(self):
        self.assertIn("ACTIVITY", self.html)
        self.assertIn("tool_use", self.html)  # raw log rendering still present
        self.assertIn("tool_result", self.html)


if __name__ == "__main__":
    unittest.main()
