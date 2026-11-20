"""Headless UI smoke test with a stub pygame: draws and taps the new screens, checks nothing raises.
   python3 tests/test_ui_smoke.py"""
import os, queue, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
import fakepygame; fakepygame.install()
from test_logic import tmpcfg


class FakeApp:
    def __init__(self):
        from buddy.gallery import PinStore
        from buddy.vault import VaultManager
        from buddy.people import PeopleStore
        from buddy.calendar_mgr import CalendarStore
        from buddy.control_center import ControlCenter
        self.cfg = c = tmpcfg(); self.size = (1024, 600); self.sim = True
        self.pins = PinStore(c); self.vault = VaultManager(c, self.pins)
        self.people = PeopleStore(c); self.cal = CalendarStore(c, self.people)
        self.ctrl = ControlCenter(c, simulate=True); self.ctrl.post = lambda fn, arg: fn(arg)
        self.toasts, self.nav, self.chosen, self.asked = [], [], [], []
        self.events = queue.Queue(); self.usb_present = True
        class Sp:
            def say(s, t): pass
            def busy(s): return False
            def stop_now(s): pass
        self.speaker = Sp()
    def toast(self, m, s=0): self.toasts.append(m)
    def back(self): self.nav.append("back")
    def choose(self, title, opts, accent=None): self.chosen.append((title, opts))
    def ask_text(self, title, initial, cb, **k): self.asked.append((title, cb))
    def confirm(self, msg, yes, *a, **k): self.chosen.append((msg, yes))
    def run_bg(self, fn, cb=None):
        r = fn()
        if cb: cb(r)
    def open(self, *a, **k): self.nav.append(a)


class Smoke(unittest.TestCase):
    def test_vault_screen_unlock_flow(self):
        from buddy.vault import VaultScreen
        a = FakeApp(); a.vault.set_secret("1234")
        s = VaultScreen(a); done = []
        s.enter(mode="unlock", on_done=done.append); s.draw(fakepygame.Surf())
        keys = s._keys()
        for ch in "9999":
            s.on_down(keys[ch].center)
        self.assertEqual(s.buf, ""); self.assertEqual(s.msg, "Wrong PIN")
        for ch in "1234":
            s.on_down(keys[ch].center)
        self.assertEqual(done, ["unlocked"]); self.assertTrue(a.vault.is_unlocked())
        s.enter(mode="unlock", on_done=done.append); s.on_down(keys["X"].center)
        self.assertEqual(done[-1], "cancel")

    def test_vault_setup_flow(self):
        from buddy.vault import VaultScreen
        a = FakeApp(); s = VaultScreen(a); done = []
        s.enter(mode="setup", on_done=done.append); k = s._keys()
        for ch in "4321": s.on_down(k[ch].center)
        for ch in "4321": s.on_down(k[ch].center)
        self.assertEqual(done, ["pin_set"]); self.assertEqual(a.vault.verify("4321"), "ok")

    def test_calendar_screen(self):
        from buddy.calendar_mgr import CalendarScreen
        from datetime import date
        a = FakeApp(); s = CalendarScreen(a); s.enter(); s.draw(fakepygame.Surf())
        cell = next(r for d, r in s._cells() if d == 15)
        s.on_down(cell.center); s.on_up(cell.center); self.assertEqual(s.sel.day, 15)
        nav = s._nav()["next"]; m0 = s.month
        s.on_down(nav.center); s.on_up(nav.center); self.assertNotEqual(s.month, m0)
        add = s._add_rect(); s.on_down(add.center); s.on_up(add.center)
        self.assertTrue(a.chosen)                                         # kind chooser opened
        s._save("birthday", "Meera", None); s._save("custom", "", None, "Trip", False)
        self.assertEqual(len(a.cal.events), 2); s.draw(fakepygame.Surf())

    def test_control_center_screen(self):
        from buddy.control_center import ControlCenterScreen
        a = FakeApp(); s = ControlCenterScreen(a); s.enter(); s.draw(fakepygame.Surf())
        add = s._add_rect(); s.on_down(add.center); s.on_up(add.center)
        title, cb = a.asked[-1]; cb("192.168.1.50")
        title, cb2 = a.asked[-1]; cb2("Bedroom")
        self.assertEqual(len(a.ctrl.nodes), 1)
        s.reload(); s.draw(fakepygame.Surf())
        tab = s._tabs()["board"]; s.on_down(tab.center); s.on_up(tab.center); self.assertEqual(s.tab, "board")
        n = a.ctrl.nodes[0]; a.ctrl.set_servo_count(n["id"], 3); s.reload(); s.draw(fakepygame.Surf())
        row = s._list_rect(); pos = (row.left + 200, row.top + 30)
        s.on_down(pos); s.on_up(pos)
        import time; time.sleep(0.6)
        self.assertEqual(n["switches"][0]["state"], "on")

    def test_text_screen_and_menu(self):
        from buddy.textview import TextScreen, md_to_lines
        a = FakeApp(); p = os.path.join(tempfile.mkdtemp(), "n.md")
        open(p, "w").write("# Title\nSome **bold** text with a [link](http://x).\n- item\n```\ncode\n```\n")
        s = TextScreen(a); s.enter(path=p); s.draw(fakepygame.Surf()); s.start_reading(); s.tick(0.1)
        self.assertEqual(md_to_lines(open(p).read())[0], ("Title", "h1"))
        from buddy.uiapps import MenuScreen
        m = MenuScreen(a); m.draw(fakepygame.Surf()); self.assertEqual(len(m._tiles()), 11)
        self.assertEqual(max(r.bottom for _, r in m._tiles()) < 600, True)

    def test_guard_swallows_errors(self):
        from buddy.util import guarded
        class X:
            app = FakeApp()
            @guarded()
            def boom(self): raise RuntimeError("x")
        x = X(); self.assertIsNone(x.boom()); self.assertTrue(x.app.toasts)


if __name__ == "__main__":
    unittest.main(verbosity=2)
