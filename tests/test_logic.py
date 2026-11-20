"""Logic tests (no screen needed):  python3 tests/test_logic.py"""
import json, os, sys, tempfile, threading, time, unittest
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import fakepygame; fakepygame.install()
import config as cfg


def tmpcfg():
    d = tempfile.mkdtemp()
    c = type("C", (), {k: getattr(cfg, k) for k in dir(cfg) if k.isupper()})
    c.DATA_DIR = d
    for k in ("CALENDAR_FILE", "CALENDAR_STATE_FILE", "ESP32_FILE", "ESP32_LOG_FILE", "VAULT_STATE_FILE", "PIN_FILE"):
        setattr(c, k, os.path.join(d, os.path.basename(getattr(cfg, k))))
    c.HIDDEN_DIR, c.GALLERY_DIR = os.path.join(d, "hidden"), os.path.join(d, "gallery")
    c.CALENDAR_REMIND_HOUR = 9
    return c


class VaultTests(unittest.TestCase):
    def test_pin_lockout_and_session(self):
        from buddy.gallery import PinStore
        from buddy.vault import VaultManager
        c = tmpcfg(); c.VAULT_LOCK_BASE_S = 30
        v = VaultManager(c, PinStore(c))
        self.assertFalse(v.is_set())
        self.assertTrue(v.set_secret("4821"))
        open(os.path.join(c.HIDDEN_DIR, "a.jpg"), "w").close()
        self.assertEqual(v.list_files(), [])               # locked -> nothing is exposed
        self.assertEqual(v.verify("0000"), "bad")
        self.assertEqual(v.verify("1111"), "bad")
        self.assertEqual(v.verify("2222"), "locked")       # third wrong try locks
        self.assertEqual(v.verify("4821"), "locked")       # even the right PIN is refused while locked
        v2 = VaultManager(c, PinStore(c))                  # reboot: lockout survives
        self.assertGreater(v2.seconds_locked(), 20)
        v2._state["locked_until"] = 0
        self.assertEqual(v2.verify("4821"), "ok")
        self.assertEqual(len(v2.list_files()), 1)
        v2.lock()
        self.assertEqual(v2.list_files(), [])

    def test_password_alnum(self):
        from buddy.gallery import PinStore
        from buddy.vault import VaultManager
        c = tmpcfg(); v = VaultManager(c, PinStore(c))
        self.assertFalse(v.set_secret("ab"))               # too short
        self.assertTrue(v.set_secret("Luna2026"))
        self.assertEqual(v.verify("luna2026"), "bad")
        self.assertEqual(v.verify("Luna2026"), "ok")


class CalendarTests(unittest.TestCase):
    def setUp(self):
        from buddy.people import PeopleStore
        from buddy.calendar_mgr import CalendarStore
        self.c = tmpcfg()
        os.makedirs(self.c.DATA_DIR, exist_ok=True)
        self.people = PeopleStore(self.c)
        self.people.enroll("Rahul", [[0.1] * 128], tier="least", jpgs=None)
        self.store = CalendarStore(self.c, self.people)

    def test_add_query_delete_link(self):
        t = date.today()
        ev = self.store.add("birthday", t.month, t.day, name="Rahul")
        self.assertEqual(ev["person"], "Rahul")
        self.assertEqual(self.people.get("Rahul")["birthday"], "%02d-%02d" % (t.month, t.day))   # linked into the profile
        self.assertEqual(len(self.store.on(t)), 1)
        self.assertEqual(len(self.store.for_person_today("rahul")), 1)
        self.assertEqual(self.store.reminder_text(ev), "Reminder: Tomorrow is Rahul's Birthday!")
        self.assertEqual(self.store.greeting_text(ev), "Happy Birthday, Rahul! Wishing you an incredible year ahead!")
        self.store.delete(ev["id"])
        self.assertNotIn("birthday", self.people.get("Rahul"))
        self.assertEqual(self.store.on(t), [])

    def test_oneoff_and_leap(self):
        self.store.add("custom", 3, 5, title="Exam", year=2031, yearly=False)
        self.assertEqual(len(self.store.on(date(2031, 3, 5))), 1)
        self.assertEqual(len(self.store.on(date(2032, 3, 5))), 0)
        self.store.add("birthday", 2, 29, name="Leap")
        self.assertEqual(len(self.store.on(date(2025, 2, 28))), 1)
        with self.assertRaises(ValueError):
            self.store.add("birthday", 2, 30, name="X")

    def test_reminder_and_once_per_day_greeting(self):
        from buddy.calendar_mgr import CalendarService
        said, spoken = [], []

        class App:
            pass
        a = App(); a.cfg, a.cal, a.state, a.greeted, a.sim = self.c, self.store, "robot", True, True
        a.events = type("Q", (), {"put": lambda s, x: spoken.append(x)})()
        a.mark_activity = lambda: None
        a.notify_text = lambda t: said.append(t)
        a.say = lambda t, e=None, s=None: spoken.append(("say", t, e))
        a.toast = lambda *x: None
        svc = CalendarService(a)
        tomorrow = date.today() + timedelta(days=1)
        self.store.add("anniversary", tomorrow.month, tomorrow.day, name="Asha & Ravi")
        self.assertFalse(svc.due_reminder(datetime.now().replace(hour=8, minute=59)))
        self.assertTrue(svc.due_reminder(datetime.now().replace(hour=9, minute=0)))
        svc.tick(datetime.now().replace(hour=9, minute=1).timestamp())
        time.sleep(0.3)
        self.assertEqual(said, ["Reminder: Tomorrow is Asha & Ravi's Anniversary!"])
        svc.tick(datetime.now().replace(hour=9, minute=5).timestamp())      # same day -> no repeat
        time.sleep(0.2)
        self.assertEqual(len(said), 1)
        t = date.today()
        self.store.add("birthday", t.month, t.day, name="Rahul")
        self.assertTrue(svc.greet("Rahul"))
        self.assertFalse(svc.greet("Rahul"))                               # only once per day
        self.assertTrue(any(s[0] == "say" and "Happy Birthday, Rahul" in s[1] and s[2] == "joy" for s in spoken if isinstance(s, tuple)))
        svc2 = CalendarService(a)                                          # restart: still remembered
        self.assertFalse(svc2.greet("Rahul"))


class FakeEsp(BaseHTTPRequestHandler):
    state = {0: "off", 1: "off"}
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path == "/api/info": self._send(200, {"name": "esp32-switch", "servos": 2})
        elif self.path == "/api/status": self._send(200, {"ok": True, "rssi": -50, "servos": [{"id": i, "state": s} for i, s in self.state.items()]})
        else: self._send(404, {})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/servo" and body.get("servo_id") in self.state and body.get("action") in ("on", "off"):
            self.state[body["servo_id"]] = body["action"]; self._send(200, {"ok": True})
        else: self._send(400, {"ok": False})


class ControlTests(unittest.TestCase):
    def test_dispatch_against_fake_firmware(self):
        from buddy.control_center import ControlCenter
        srv = HTTPServer(("127.0.0.1", 0), FakeEsp); threading.Thread(target=srv.serve_forever, daemon=True).start()
        c = tmpcfg(); cc = ControlCenter(c)
        n = cc.add_node("127.0.0.1", "Bedroom", servos=2); n["port"] = srv.server_port
        self.assertEqual(len(cc.all_switches()), 2)
        cc.rename_switch(n["id"], 0, "Light"); cc.rename_switch(n["id"], 1, "Fan")
        self.assertEqual(cc.resolve_phrase("fan")[1]["servo"], 1)
        self.assertEqual(cc.resolve_phrase("switch")[1]["servo"], 0)
        self.assertIsNone(cc.resolve_phrase("heater"))
        res = []; ev = threading.Event()
        cc.set_switch(n["id"], 0, True, lambda ok, msg, nn, sw: (res.append((ok, msg, sw["state"])), ev.set()))
        self.assertTrue(ev.wait(5)); self.assertEqual(res[0], (True, "OK", "on"))
        self.assertEqual(FakeEsp.state[0], "on")
        self.assertTrue(cc.refresh_one(n)); self.assertTrue(cc.online(n["id"]))
        cc.set_servo_count(n["id"], 4); self.assertEqual(len(n["switches"]), 4); self.assertEqual(n["switches"][0]["name"], "Light")
        srv.shutdown()
        res.clear(); ev.clear()                                           # server gone -> graceful failure
        cc.set_switch(n["id"], 0, False, lambda ok, msg, nn, sw: (res.append((ok, msg)), ev.set()))
        self.assertTrue(ev.wait(8)); self.assertFalse(res[0][0]); self.assertFalse(cc.online(n["id"]))
        self.assertTrue(os.path.exists(c.ESP32_LOG_FILE))


class TelegramTests(unittest.TestCase):
    def make(self):
        from buddy.telegram_bot import TelegramBot
        c = tmpcfg(); os.makedirs(c.GALLERY_DIR, exist_ok=True)
        calls = []
        class Tg: token, chat_id = "123:ABC", "42"; configured = lambda s: True
        class Sec:
            enabled = False; telegram = Tg()
            siren = type("S", (), {"active": False})()
            pending = lambda s: 2
        class App: pass
        a = App(); a.cfg, a.sec, a.sim, a.net = c, Sec(), True, type("N", (), {"online": True})()
        a.events = __import__("queue").Queue()
        a.on_telegram_media = lambda p: None
        a.sensors = type("Z", (), {"snapshot": lambda s: dict(temperature=27.4, humidity=55, pressure=913, pressure_src="BMP280", aq_label="Good", aq_pct=8,
                                                              has_analog=True, has_bmp=True, gas_alert=False, comfort="Comfortable")})()
        return TelegramBot(a), a, c

    def test_auth_and_commands(self):
        bot, a, c = self.make()
        bot.handle({"chat": {"id": 999}, "text": "/arm_alarm"})
        self.assertTrue(a.events.empty() and not bot.sent)                  # stranger ignored
        bot.handle({"chat": {"id": 42}, "text": "/arm_alarm"})
        self.assertFalse(a.events.empty()); self.assertIn("ARMED", bot.sent[-1][1])
        bot.handle({"chat": {"id": 42}, "text": "/room_status"})
        r = bot.sent[-1][1]
        for s in ("27.4", "55", "913", "BMP280", "Good", "8%"): self.assertIn(s, r)
        bot.handle({"chat": {"id": 42}, "text": "/alarm_status"}); self.assertIn("DISARMED", bot.sent[-1][1])

    def test_gas_alert_rate_limit(self):
        bot, a, c = self.make(); c.GAS_ALERT_REPEAT_S = 300
        snap = dict(gas_alert=True, aq_pct=61, has_analog=True, aq_label="Poor", temperature=30, humidity=40)
        bot.gas_tick(snap, 1000.0); time.sleep(0.2)
        self.assertIn("ALERT: Gas/Smoke detected!", bot.sent[-1][1]); self.assertIn("61%", bot.sent[-1][1])
        n = len(bot.sent); bot.gas_tick(snap, 1100.0); time.sleep(0.2); self.assertEqual(len(bot.sent), n)   # no spam
        bot.gas_tick(snap, 1400.0); time.sleep(0.2); self.assertEqual(len(bot.sent), n + 1)                   # repeat after 5 min
        bot.gas_tick(dict(gas_alert=False), 1500.0); time.sleep(0.2); self.assertIn("clear", bot.sent[-1][1])

    def test_media_detection(self):
        from buddy.telegram_bot import TelegramBot as T
        self.assertEqual(T._media_of({"photo": [{"file_id": "a", "file_size": 1}, {"file_id": "b", "file_size": 9}]})[:3], ("photo", "b", ".jpg"))
        self.assertEqual(T._media_of({"video": {"file_id": "v"}})[:3], ("video", "v", ".mp4"))
        self.assertEqual(T._media_of({"document": {"file_id": "d", "mime_type": "image/png", "file_name": "x.png"}})[2], ".png")
        self.assertIsNone(T._media_of({"document": {"file_id": "d", "mime_type": "application/zip", "file_name": "x.zip"}}))

    def test_download_to_gallery(self):
        import requests
        bot, a, c = self.make()
        class R:
            ok = True; status_code = 200
            def json(s): return {"result": {"file_path": "photos/f.jpg"}}
            def raise_for_status(s): pass
            def iter_content(s, n): yield b"JPEGDATA"
            def __enter__(s): return s
            def __exit__(s, *a): pass
        bot._api = lambda *x, **k: R()
        orig = requests.get; requests.get = lambda *x, **k: R()
        try:
            p = bot.download_media("photo", "id", ".jpg", 1000)
        finally:
            requests.get = orig
        self.assertTrue(p.startswith(c.GALLERY_DIR) and os.path.exists(p) and not os.path.exists(p + ".part"))
        kind, (fn, arg) = a.events.get_nowait(); self.assertEqual(arg, p)
        bot.download_media("video", "id", ".mp4", 50 * 1024 * 1024); self.assertIn("bigger", bot.sent[-1][1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
