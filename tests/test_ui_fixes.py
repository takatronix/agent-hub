"""Static (string-inspection) tests for the 7 embedded-JS fixes in agent_hub/ui.py.

The UI is a single inline HTML/JS blob (ui.INDEX_HTML). We cannot execute the JS
here, so each fix is verified by asserting that the vulnerable/old raw pattern is
gone and the new helper/guard is present in the served markup.
"""
import unittest

from agent_hub import ui

HTML = ui.INDEX_HTML


class UIFixesTest(unittest.TestCase):
    def test_is_string(self):
        self.assertIsInstance(HTML, str)
        self.assertIn("function md(", HTML)

    # ---- Bug 2: agent-name JS injection (jesc + no raw ${n}/${a.name} in handlers) ----
    def test_jesc_helper_exists(self):
        self.assertIn("const jesc=", HTML)
        # esc must now also escape the single quote (so attribute/JS-string contexts are safe)
        self.assertIn("'&#39;'", HTML)

    def test_no_raw_name_in_inline_handlers(self):
        # the old raw interpolations must be gone
        self.assertNotIn("models['${n}']", HTML)
        self.assertNotIn("toggleAgent('${n}')", HTML)
        self.assertNotIn("toggleAgent('${a.name}')", HTML)
        self.assertNotIn("forgetAgent('${a.name}')", HTML)

    def test_handlers_use_jesc(self):
        self.assertIn("models['${jesc(n)}']", HTML)
        self.assertIn("toggleAgent('${jesc(n)}')", HTML)
        self.assertIn("toggleAgent('${jesc(a.name)}')", HTML)
        self.assertIn("forgetAgent('${jesc(a.name)}')", HTML)

    # ---- Bug 1: stored XSS via RUN.spec.parent_run breadcrumb ----
    def test_parent_run_validated(self):
        # no longer interpolated raw into href/onclick
        self.assertNotIn("/runs/${RUN.spec.parent_run}", HTML)
        # run-id format guard is present
        self.assertIn(r"/^run_[0-9a-f]+$/", HTML)
        self.assertIn("prOk", HTML)

    # ---- Bug 3: UTC -> local time via new Date() ----
    def test_time_uses_date(self):
        # the old naive one-line definitions (that sliced the raw ISO string as the
        # ONLY behaviour) are gone
        self.assertNotIn("const fmtTs=t=>t?t.slice(11,19):'';", HTML)
        self.assertNotIn("const fmtDt=t=>t?t.replace('T',' ').slice(5,16):'';", HTML)
        # new Date()-based local-time formatting is present
        self.assertIn("new Date(t)", HTML)
        self.assertIn("const p2=", HTML)
        self.assertIn("d.getHours()", HTML)
        self.assertIn("d.getMonth()", HTML)

    # ---- Bug 4: bodyKey reset in showRun ----
    def test_bodykey_reset(self):
        self.assertIn("childrenLoaded=false;bodyKey='';", HTML)

    # ---- Bug 5: cols view render key includes status unconditionally ----
    def test_cols_key_includes_status(self):
        self.assertNotIn("t.id+':'+(view==='results'?t.status:'')", HTML)
        self.assertIn("t.id+':'+t.status", HTML)

    # ---- Bug 6: inline code stashed as placeholder (decorations don't fire inside) ----
    def test_inline_code_stashed(self):
        E0 = chr(0xE000)
        E1 = chr(0xE001)
        # inline code no longer converted directly to <code>...</code> before ** / * pass
        self.assertNotIn("/`([^`\\n]+)`/g,'<code>$1</code>'", HTML)
        # inline code pushed into the same blocks[] array with a placeholder
        self.assertIn("blocks.push(`<code>${c}</code>`)", HTML)
        # a distinct sentinel is used for inline code so a lone inline-code line is not
        # treated as a block-level placeholder and left bare
        self.assertIn(E1, HTML)
        # block-level line check uses the fenced sentinel form
        self.assertIn("/^" + E0 + r"\d+" + E0 + "$/", HTML)
        # restore strips both sentinels
        self.assertIn("[" + E0 + E1 + r"](\d+)[" + E0 + E1 + "]", HTML)

    # ---- Bug 7: SSE reconnect re-sync ----
    def test_connect_takes_onsync(self):
        self.assertIn("function connect(runId,onSync)", HTML)
        self.assertIn("if(onSync)", HTML)

    def test_showrun_passes_resync(self):
        self.assertIn("const resync=", HTML)
        self.assertIn("connect(id,resync)", HTML)
        # resync refetches run + messages after lastId
        self.assertIn("/messages?after=${lastId}", HTML)


if __name__ == "__main__":
    unittest.main()
