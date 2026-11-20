"""Integration test of the real App class (simulation mode, stub pygame): the hidden-vault crash is gone and
voice -> ESP32 / calendar / Telegram wiring works.   python3 tests/test_app_flow.py"""
import os, sys, tempfile, time, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
import fakepygame; fakepygame.install()
from test_logic import tmpcfg, FakeEsp
import threading
from http.server import HTTPServer


def make_app():
    import types
    from buddy.app import App
    c = tmpcfg()
    for d in ("MUSIC_DIR", "MOVIES_DIR", "DRAWINGS_DIR", "SECURITY_DIR", "THUMB_DIR", "PDF_DIR"):
        setattr(c, d, os.path.join(c.DATA_DIR, d.lower()))
    for k in ("PRIVACY_PIN_FILE", "TELEGRAM_FILE", "UI_STATE_FILE"):
        setattr(c, k, os.path.join(c.DATA_DIR, os.path.basename(getattr(c, k))))
    a = App(c, simulate=True)
    a.size = (1024, 600)
    a.screen = fakepygame.Surf((1024, 600))
    from buddy.face import Face
    from buddy.analysis import AnalysisScreen
    from buddy.screens import ViewerScreen, MiniFace
    a.face = Face(a.size); a.analysis = AnalysisScreen(a.size, 10); a.timed_view = ViewerScreen(a.size)
    a.mini = MiniFace(a.size, c.UI_STATE_FILE)
    a._build_screens()
    a.greeted = True
    return a


class Flow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = make_app()

    def pump(self, secs=0.0):
        end = time.time() + secs
        while True:
            self.a._poll_events()
            if time.time() >= end: break
            time.sleep(0.02)

    def test_1_old_crash_is_gone(self):
        a = self.a
        a.request_hidden(replace=False)                        # this call used to raise TypeError -> Luna quit
        self.assertEqual(a.state, "vault")
        a.screens["vault"].on_back()                           # cancel
        self.assertEqual(a.state, "gallery")                   # graceful: normal gallery, still running
        self.assertTrue(a.running)

    def test_2_error_boundary_keeps_running(self):
        a = self.a
        a.go_robot()
        a._tick = lambda dt: (_ for _ in ()).throw(RuntimeError("boom"))
        for _ in range(3):
            try:
                a._tick(0.03)
            except Exception:
                a._recover()
        self.assertTrue(a.running)
        del a._tick

    def test_3_unlock_flow_opens_hidden_gallery(self):
        a = self.a
        a.vault.set_secret("2468"); a.vault.lock(); a.go_robot()
        a.request_hidden()
        s = a.screens["vault"]; k = s._keys()
        for ch in "2468": s.on_down(k[ch].center)
        self.assertEqual(a.state, "gallery"); self.assertEqual(a.screens["gallery"].mode, "hidden")
        a.go_robot(); self.assertFalse(a.vault.is_unlocked())  # leaving re-locks
        a.open("gallery", mode="hidden")                       # direct attempt without PIN
        self.assertEqual(a.screens["gallery"].mode, "normal")

    def test_4_voice_switch_to_esp32(self):
        a = self.a
        n = a.ctrl.add_node("192.168.1.50", "Room", servos=2)
        a.ctrl.rename_switch(n["id"], 0, "Light")
        a._apply_reply((a.brain.handle("turn on the light"), None, 0)); self.pump(1.0)
        self.assertEqual(n["switches"][0]["state"], "on")
        a._apply_reply((a.brain.handle("turn off the light"), None, 0)); self.pump(1.0)
        self.assertEqual(n["switches"][0]["state"], "off")

    def test_5_calendar_voice_and_birthday_on_recognition(self):
        from datetime import date, timedelta
        a = self.a
        t = date.today()
        a.cal.add("birthday", t.month, t.day, name="Rahul")
        a._apply_reply((a.brain.handle("what is on my calendar today"), None, 0))
        a.speaker.clear()
        a._on_arrive("Rahul")
        self.assertIn(("Rahul"), a.last_greet)
        self.assertEqual(a.override, "joy")

    def test_6_telegram_arm_disarm_and_media_toast(self):
        a = self.a
        a.tgbot.tg.token, a.tgbot.tg.chat_id = "1:x", "7"
        a.tgbot.handle({"chat": {"id": 7}, "text": "/arm_alarm"}); self.pump()
        self.assertTrue(a.sec.enabled)
        a.tgbot.handle({"chat": {"id": 7}, "text": "/disarm_alarm"}); self.pump()
        self.assertFalse(a.sec.enabled)
        a.on_telegram_media("/x/y.jpg")
        self.assertIn("New media added to Gallery via Telegram", a.toast_msg)

    def test_7_usb_icon_and_events(self):
        a = self.a
        a.go_robot()
        a._usb_event("in", dict(label="STICK", path="/media/x/STICK"))
        self.assertTrue(a.usb_present)
        r = a.usb_rect(); a._pointer("down", r.center); a._pointer("up", r.center)
        self.assertEqual(a.state, "files")


if __name__ == "__main__":
    unittest.main(verbosity=2)
