"""Main application: robot face, menu + apps, voice, touch, camera, people, security."""
import logging
import os
import queue
import random
import re
import subprocess
import sys
import threading
import time

import pygame

from . import brain as brainmod
from .analysis import AnalysisScreen
from .audio import AudioRouter, BluetoothKeeper, Speaker
from .camera import CameraService, SimCamera
from .display_ctl import DisplayControl
from . import files as F
from .face import Face, font
from .fileapps import FilesScreen, PdfScreen
from .gallery import GalleryStore, PinStore
from .media import VideoLibrary, VideoPlayer, import_from_usb, is_video
from .mediaapps import (AnalysisApp, CameraAppScreen, DrawingCanvas, DrawingGallery, GalleryApp, MoviesScreen, MusicScreen, VideoPlayScreen)
from .music import MusicLibrary, make_player
from .netmgr import BluetoothManager, WifiManager
from .people import LEAST, MASTER, PRIORITY, PeopleStore, RANK_UNKNOWN, clean_name, rank_label
from .screens import MiniFace, ViewerScreen, draw_photo, inside
from .security import SecurityManager
from .sensors import SensorHub
from .touch import TouchPad
from .ui import ConfirmScreen, KeyboardScreen, ListView, icon
from .uiapps import (AboutScreen, BluetoothScreen, CaptureScreen, ChoiceScreen, DisplayScreen, MenuScreen, PersonScreen, PinScreen,
                     PrivacyScreen, SecurityScreen, SettingsScreen, TelegramScreen, WifiScreen)
from .util import NetMonitor, mix, state_load, state_save, time_greeting
from .vault import VaultManager, VaultScreen
from .usbmon import USBMonitor, safe_eject
from .textview import TextScreen
from .calendar_mgr import CalendarScreen, CalendarService, CalendarStore
from .control_center import ControlCenter, ControlCenterScreen
from .telegram_bot import TelegramBot

log = logging.getLogger("app")
ROBOT, ANALYSIS_TIMED, EXITING, PHOTO, IMAGE_TIMED = "robot", "analysis_timed", "exiting", "photo", "image_timed"

ACTION_PERM = {"analysis": "chat", "sleep": "control", "wake": "control", "volume": "control", "timer": "control",
               "photo": "photo", "show_image": "gallery", "gallery": "gallery", "close_gallery": "chat", "hidden_gallery": "hidden_gallery",
               "change_pin": "hidden_gallery", "introduce": "introduce", "whoami": "chat", "who_visible": "chat", "list_people": "chat",
               "music": "apps", "movie": "apps", "mctl": "apps", "album": "apps", "record": "photo", "security": "manage_people",
               "alarm": "manage_people", "back": "chat", "home": "chat", "comment": "chat", "pdf": "apps", "pdfctl": "apps", "usb": "gallery", "switch": "switches", "calendar": "calendar"}
OPEN_PERM = {"settings": "settings", "privacy": "settings", "about": "settings", "wifi": "settings", "bluetooth": "settings", "display": "settings",
             "security": "settings", "gallery": "gallery", "camera": "photo", "music": "apps", "movies": "apps", "drawing": "apps",
             "analysis": "apps", "menu": "chat", "documents": "apps", "usb": "gallery", "calendar": "calendar", "control": "control_center"}
NEED_TEXT = {0: "my masters", 1: "my master and priority people", 2: "my master and priority people", 3: "people I know", 4: "everyone"}


class App:
    def __init__(self, cfg, simulate=False):
        self.cfg, self.sim = cfg, simulate
        self.events = queue.Queue()
        self.state = ROBOT
        self.nav = []
        self.running = True
        now = time.time()
        self.start_time = self.last_activity = self.ui_last = now
        self.asleep = False
        self.override, self.override_until = None, 0.0
        self.listening_until = self.window_until = 0.0
        self.thinking = False
        self.idle_emotion, self.idle_until, self.next_idle = "neutral", 0.0, now + 15
        self.timers = []
        self.exit_target, self.exit_deadline = None, 0.0
        self.alert_active, self.last_alert_voice = False, 0.0
        self.comment_at, self.greeted, self.prev_speaking = {}, False, False
        self.ripples = []
        self.finger_down = self.mini_active = self.menu_down = False
        self.last_photo = None
        self.photo = None
        self.timed_view = None
        self._ret = ROBOT
        self.last_greet, self.last_unknown_ask = {}, 0.0
        self.awaiting_name_until = 0.0
        self.last_enroll = (None, 0.0)
        self.snap = {}
        self.toast_msg, self.toast_until = "", 0.0
        self.wifi_status, self.bt_status = "not connected", "not connected"
        self.shuffle = False
        self._music_before_video = False
        self.intruder = None
        self.unknown_last_seen = 0.0
        self.screens = {}
        self.size = None
        self.usb_present, self.usb_down = False, False
        self._err_times = []

        self.net = NetMonitor(force=True if simulate else None)
        self.router = AudioRouter(cfg)
        self.btkeeper = BluetoothKeeper(cfg)
        self.speaker = Speaker(cfg, self.router, self.net, simulate)
        self.sensors = SensorHub(cfg, simulate, self.net)
        self.touch = TouchPad(cfg, simulate)
        self.people = PeopleStore(cfg)
        self.store = GalleryStore(cfg)
        self.pins = PinStore(cfg)
        self.ppins = PinStore(cfg, cfg.PRIVACY_PIN_FILE)
        if not self.ppins.is_set():
            self.ppins.set(cfg.PRIVACY_PIN_INITIAL)
        self.camera = SimCamera(cfg, self.people) if simulate else CameraService(cfg, self.people)
        self.mlib = MusicLibrary(cfg)
        self.player = make_player(cfg, simulate)
        self.vlib = VideoLibrary(cfg)
        self.video = VideoPlayer(cfg, simulate)
        self.wifi = WifiManager(simulate)
        self.bt = BluetoothManager(simulate)
        self.display = DisplayControl(cfg, simulate)
        self.sec = SecurityManager(cfg, self.net, simulate)
        self.sec.siren.on_gap = self._siren_gap
        self.vault = VaultManager(cfg, self.pins)
        self.cal = CalendarStore(cfg, self.people)
        self.cal_service = CalendarService(self)
        self.ctrl = ControlCenter(cfg, simulate)
        self.ctrl.post = lambda fn, arg: self.events.put(("call", (fn, arg)))
        self.ctrl.on_found = lambda n: (self.toast("Found ESP32: %s" % n["name"], 4), self.say("I found a new switch node named %s." % n["name"], "surprised"))
        self.tgbot = TelegramBot(self)
        self.usbmon = USBMonitor(cfg, self.events, simulate)
        self.brain = brainmod.Brain(cfg, self.sensors.snapshot, lambda: self.net.online, self.people.names)
        self.brain.switch_names = self.ctrl.switch_names
        st = state_load(cfg)
        self.display.set(st.get("brightness", 100))
        self.router.volume = st.get("volume", cfg.DEFAULT_VOLUME)
        if simulate:
            from .voice import ConsoleListener
            self.listener = ConsoleListener(self._on_text)
        else:
            from .voice import Listener
            self.listener = Listener(cfg, self._on_text, self._on_partial, is_paused=self._mic_paused)

    def _mic_paused(self):
        return self.speaker.speaking or time.time() < self.speaker.quiet_until or self.sec.siren.sounding

    # ============================================================ lifecycle
    def run(self):
        cfg = self.cfg
        pygame.init()
        pygame.mouse.set_visible(False)
        self.screen = pygame.display.set_mode((0, 0) if cfg.FULLSCREEN else cfg.WINDOW_SIZE, pygame.FULLSCREEN if cfg.FULLSCREEN else 0)
        pygame.display.set_caption("Luna")
        self.size = size = self.screen.get_size()
        log.info("display size %s", size)
        self.face = Face(size)
        self.analysis = AnalysisScreen(size, cfg.ANALYSIS_SECONDS)
        self.timed_view = ViewerScreen(size)
        self.mini = MiniFace(size, cfg.UI_STATE_FILE)
        self._build_screens()
        clock = pygame.time.Clock()
        for th in (self.net, self.sensors, self.speaker, self.listener, self.camera):
            th.start()
        if not self.sim:
            self.btkeeper.start()
        self.usb_present = bool(F.usb_drives(cfg))
        self.usbmon.start()
        self.ctrl.start()
        self.tgbot.start()
        self.run_bg(self.wifi.active, lambda a: setattr(self, "wifi_status", a or "not connected"))
        self.run_bg(lambda: [d["name"] for d in self.bt.devices() if d["connected"]],
                    lambda l: setattr(self, "bt_status", ", ".join(l) if l else "not connected"))
        self.face.set_emotion("surprised")
        try:
            while self.running:
                dt = clock.tick(cfg.FPS) / 1000.0
                try:                                   # ONE bad frame / tap must never close Luna
                    self._handle_pygame_events()
                    self._poll_events()
                    self._tick(dt)
                    self._draw()
                    pygame.display.flip()
                except Exception:
                    self._recover()
        finally:
            self._cleanup()

    def _build_screens(self):
        classes = [MenuScreen, SettingsScreen, ChoiceScreen, PinScreen, KeyboardScreen, ConfirmScreen, PrivacyScreen, PersonScreen, CaptureScreen,
                   AboutScreen, WifiScreen, BluetoothScreen, DisplayScreen, SecurityScreen, TelegramScreen, GalleryApp, MoviesScreen, VideoPlayScreen,
                   MusicScreen, CameraAppScreen, DrawingGallery, DrawingCanvas, AnalysisApp, PdfScreen, FilesScreen,
                   VaultScreen, TextScreen, CalendarScreen, ControlCenterScreen]
        for c in classes:
            s = c(self)
            self.screens[s.name] = s

    def _cleanup(self):
        log.info("shutting down UI (target=%s)", self.exit_target)
        try:
            self.speaker.clear()
            self.sec.siren.stop()
            self.usbmon.stop()
            self.ctrl.stop()
            self.tgbot.stop()
            self.player.stop()
            self.video.stop()
            self.camera.stop_recording()
            pygame.quit()
        except Exception:
            pass
        if self.exit_target == "calibration" and not self.sim:
            script = os.path.join(self.cfg.BASE_DIR, "tools", "calibrate_mq2.py")
            try:
                subprocess.Popen(["lxterminal", "-e", "bash -c '%s %s; read -p Done'" % (sys.executable, script)])
            except Exception as e:
                log.warning("could not open calibration terminal: %s", e)

    # ============================================================ navigation
    def open(self, _screen, **kw):
        name = _screen
        if self.state != name:
            if self.state in self.screens:
                self.nav.append(self.state)
            elif self.state in (ROBOT,):
                self.nav = []
        scr = self.screens[name]
        scr.enter(**kw)
        self.mini.snap(scr.mini_pos)
        self.state = name
        self.ui_last = self.last_activity = time.time()
        self.mini_active = False
        self.mark_activity()

    def back(self):
        cur = self.screens.get(self.state)
        if cur:
            cur.leave()
        if self.nav:
            self.state = self.nav.pop()
            prev = self.screens[self.state]
            self.mini.snap(prev.mini_pos)
            if hasattr(prev, "resume"):
                prev.resume()
            elif hasattr(prev, "reload"):
                prev.reload()
        else:
            self.go_robot(leave=False)
        self.ui_last = time.time()

    def go_robot(self, leave=True):
        cur = self.screens.get(self.state)
        if cur and leave:
            cur.leave()
        self.nav = []
        self.state = ROBOT
        self.mini_active = False
        self.mark_activity()

    def screen_context(self):
        scr = self.screens.get(self.state)
        if scr:
            return scr.context(), scr.comment()
        return "The robot face screen.", ""

    def toast(self, msg, secs=2.6):
        self.toast_msg, self.toast_until = msg, time.time() + secs

    def run_bg(self, fn, cb=None):
        def work():
            try:
                res = fn()
            except Exception as e:
                log.warning("background job failed: %s", e)
                res = None
            if cb:
                self.events.put(("call", (cb, res)))
        threading.Thread(target=work, daemon=True).start()

    def ask_text(self, title, initial, cb, password=False, hint="", maxlen=64):
        self.open("keyboard", title=title, initial=initial, cb=cb, password=password, hint=hint, maxlen=maxlen)

    def confirm(self, msg, on_yes, yes_label="Yes", danger=False):
        self.open("confirm", msg=msg, on_yes=on_yes, yes_label=yes_label, danger=danger)

    def choose(self, title, options, accent=None):
        from .screens import BLUE
        self.open("choice", title=title, options=options, accent=accent or BLUE)

    def require_pin(self, kind, on_ok):
        store, label = (self.ppins, "Privacy PIN") if kind == "privacy" else (self.pins, "Hidden gallery PIN")
        mode = "unlock" if store.is_set() else "setup"
        self.open("pin", mode=mode, pins=store, label=label,
                  on_done=lambda res: on_ok() if res in ("unlocked", "pin_set") else None)

    # ============================================================ people / permissions
    def current(self):
        return self.camera.current_person()

    def restricted(self):
        if not self.people.has_master():
            return False
        if not self.camera.available and not getattr(self.cfg, "LOCK_WITHOUT_CAMERA", False):
            return False
        return True

    def allowed(self, perm, rank):
        return (not self.restricted()) or rank <= self.cfg.PERMISSIONS.get(perm, 4)

    def deny(self, perm, person):
        need = self.cfg.PERMISSIONS.get(perm, 4)
        if person:
            self.say("Sorry %s, that is only for %s." % (person["name"], NEED_TEXT[need]), "sad")
        else:
            self.say("Sorry, I only do that for %s. Please introduce yourself first so I can learn your face." % NEED_TEXT[need], "sad")

    def require(self, perm):
        person, rank = self.current()
        if self.allowed(perm, rank):
            return True
        self.deny(perm, person)
        return False

    # ============================================================ input
    def _handle_pygame_events(self):
        for ev in pygame.event.get():
            try:
                self._one_event(ev)
            except Exception:
                self._recover()

    def _one_event(self, ev):
        if True:
            if ev.type == pygame.QUIT:
                self.running = False
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    self.exit_target, self.running = "os", False
                elif ev.key == pygame.K_SPACE:
                    self.touch.press()
                elif ev.key == pygame.K_a:
                    self.events.put(("analysis", True))
                elif ev.key == pygame.K_g and self.sim:
                    self.sensors.sim_gas = not self.sensors.sim_gas
            elif ev.type == pygame.KEYUP and ev.key == pygame.K_SPACE:
                self.touch.release()
            elif self.cfg.TOUCHSCREEN_ENABLED and ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                self._pointer("down", ev.pos)
            elif self.cfg.TOUCHSCREEN_ENABLED and ev.type == pygame.MOUSEMOTION and self.finger_down:
                self._pointer("move", ev.pos)
            elif self.cfg.TOUCHSCREEN_ENABLED and ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                self._pointer("up", ev.pos)

    def hamburger_rect(self):
        u = self.size[1] / 600.0
        return pygame.Rect(int(self.size[0] / 2 - 38 * u), int(10 * u), int(76 * u), int(54 * u))

    def usb_rect(self):
        r = self.hamburger_rect()
        return pygame.Rect(r.right + int(14 * self.size[1] / 600.0), r.top, r.width, r.height)

    def _pointer(self, kind, pos):
        if kind == "down":
            self.finger_down = True
        elif kind == "up":
            self.finger_down = False
        now = time.time()
        scr = self.screens.get(self.state)
        if scr is not None:
            self.ui_last = self.last_activity = now
            if self._pointer_mini(kind, pos, scr):
                return
            getattr(scr, kind)(pos)
            return
        if self.state == ROBOT:
            ur = self.usb_rect().inflate(30, 20)
            if kind == "down" and self.usb_present and inside(pos, ur):
                self.usb_down = True
                return
            if self.usb_down:
                if kind == "up":
                    self.usb_down = False
                    if inside(pos, ur):
                        self.mark_activity()
                        self.open_app("usb")
                return
            hr = self.hamburger_rect().inflate(30, 20)
            if kind == "down" and inside(pos, hr):
                self.menu_down = True
                return
            if self.menu_down:
                if kind == "up":
                    self.menu_down = False
                    if inside(pos, hr):
                        self.mark_activity()
                        self.open("menu")
                return
            if kind == "down":
                self._screen_touch(pos)
            elif kind == "up":
                self.touch.release()
        elif self.state == ANALYSIS_TIMED:
            if kind == "down":
                self._screen_touch(pos)
            elif kind == "up":
                self.touch.release()

    def _pointer_mini(self, kind, pos, scr):
        if not scr.mini:
            return False
        if kind == "down" and self.mini.hit(pos) and not scr.priority_hit(pos):
            self.mini_active = True
            self.mini.down(pos)
            return True
        if not self.mini_active:
            return False
        if kind == "move":
            self.mini.move(pos)
        elif kind == "up":
            self.mini_active = False
            res = self.mini.up(pos)
            if res == "double":
                self.go_robot()
            elif res == "tap":
                self.show("joy", 1.5)
        return True

    def _screen_touch(self, pos):
        w, h = self.screen.get_size()
        self.ripples = (self.ripples + [(pos[0], pos[1], time.time())])[-4:]
        self.touch.press()
        if self.state == ROBOT:
            self.face.look_at((pos[0] - w / 2) / (w / 2), (pos[1] - h * 0.45) / (h / 2))
            if not self.asleep:
                self.show("surprised", 0.45)

    def _on_text(self, text):
        self.events.put(("text", text))

    def _on_partial(self, text):
        self.events.put(("partial", text))

    def _poll_events(self):
        for kind in self.touch.poll():
            self.events.put(("touch", kind))
        while True:
            try:
                ev = self.camera.events.get_nowait()
            except queue.Empty:
                break
            if ev[0] == "arrive":
                self._on_arrive(ev[1])
            elif ev[0] == "unknown":
                self._on_unknown()
        while True:
            try:
                kind, val = self.events.get_nowait()
            except queue.Empty:
                return
            if kind == "text":
                self._process_text(val)
            elif kind == "partial":
                self.listening_until = time.time() + 1.2
            elif kind == "touch":
                self._on_touch(val)
            elif kind == "reply":
                self._apply_reply(val)
            elif kind == "analysis":
                self.enter_analysis(speak=True)
            elif kind == "say":
                self.say(*val)
            elif kind == "call":
                val[0](val[1])
            elif kind == "usb":
                self._usb_event(*val)

    def _sim_command(self, text):
        parts = text[1:].split(None, 1)
        if parts and parts[0] == "see":
            names = [n.strip() for n in (parts[1] if len(parts) > 1 else "").split(",") if n.strip()]
            self.camera.set_view([clean_name(n) for n in names if n != "?"], unknown="?" in names)
        elif parts and parts[0] == "none":
            self.camera.set_view([], False)

    # ============================================================ behaviour
    def mark_activity(self):
        self.last_activity = time.time()
        if self.asleep:
            self.asleep = False
            self.show("surprised", 1.5)

    def show(self, emotion, seconds=3.0):
        self.override, self.override_until = emotion, time.time() + seconds

    def say(self, text, emotion=None, seconds=None):
        if emotion:
            self.show(emotion, seconds or (len(text) * 0.075 + 2.0))
        self.speaker.say(text)

    # ---- speech / text
    def _process_text(self, text):
        t = brainmod.norm(text)
        if text.startswith("!"):
            self._sim_command(text)
            return
        if not t:
            return
        person, rank = self.current()
        target = brainmod.system_command(t)
        if target:
            if self.allowed("system", rank):
                self.do_exit(target)
            else:
                self.deny("system", person)
            return
        now = time.time()
        woke, rest = brainmod.strip_wake(t, self.cfg.WAKE_WORDS)
        if now < self.last_enroll[1] and re.match(r"^(no|wrong|incorrect|that is wrong|that's wrong|that is not my name|that's not my name|not my name)\b", t):
            self._undo_enroll()
            return
        if now < self.awaiting_name_until and not woke:
            name = brainmod.parse_name(rest, allow_bare=True)
            if name:
                self.awaiting_name_until = 0.0
                if self.intruder:
                    self.intruder["named"] = True
                    self.sec.siren.stop()
                threading.Thread(target=self._introduce, args=(name,), daemon=True).start()
                return
        if self.cfg.REQUIRE_WAKE_WORD and not (woke or now < self.window_until):
            return
        if self.asleep and not woke:
            return
        self.mark_activity()
        self.listening_until = now + 1.0
        if woke and not rest:
            self.window_until = now + 8
            self.say(("Yes %s?" % person["name"]) if person else "Yes? I am listening.", "happy", 2.5)
            return
        self.thinking = True
        ctx, comm = self.screen_context()
        self.brain.screen_ctx, self.brain.screen_comment = ctx, comm
        threading.Thread(target=self._think, args=(rest, person), daemon=True).start()

    def _think(self, text, person):
        rank = self.people.rank(person)
        reply = self.brain.handle(text, {"name": person["name"]} if person else None)
        self.events.put(("reply", (reply, person, rank)))

    def _perm_for(self, act):
        key = act.split(":")[0]
        if key == "usb" and act.endswith("backup"):
            return "manage_people"
        if key == "open":
            return OPEN_PERM.get(act.split(":")[1], "apps")
        return ACTION_PERM.get(key, "chat")

    def _apply_reply(self, payload):
        r, person, rank = payload
        self.thinking = False
        act = r.action or ""
        key = act.split(":")[0]
        if not self.allowed(self._perm_for(act), rank):
            self.deny(self._perm_for(act), person)
            return
        if key in ("introduce", "whoami", "who_visible", "list_people"):
            self._people_action(act, person)
            return
        if key == "analysis":
            self.enter_analysis(speak=False)
            self.say(self.brain.summary() if self.cfg.SPEAK_ANALYSIS else r.text, r.emotion, 4)
            return
        if key in ("music", "movie"):
            self._voice_play(act, r)
            return
        if key == "switch":
            self._switch_action(act.split(":")[1], ":".join(act.split(":")[2:]))
            return
        if key == "calendar":
            self._calendar_action(act.split(":")[1])
            return
        text = r.text
        if person and not act and r.emotion != "confused" and person["name"] not in text and random.random() < 0.35 and text:
            text = "%s, %s%s" % (person["name"], text[0].lower(), text[1:])
        if text:
            self.say(text, r.emotion)
        parts = act.split(":")
        if key == "sleep":
            self.asleep = True
        elif key == "wake":
            self.asleep = False
        elif key == "volume":
            self.router.change_volume(int(parts[1]))
            self.router._vol_applied = None
        elif key == "timer":
            self.timers.append(time.time() + int(parts[1]))
        elif key == "photo":
            self.start_photo(parts[1])
        elif key == "show_image":
            self.show_last_image()
        elif key == "gallery":
            self.open("gallery", mode="normal")
        elif key == "close_gallery":
            self.go_robot()
        elif key == "hidden_gallery":
            self.request_hidden()
        elif key == "change_pin":
            self.open("pin", mode="change" if self.pins.is_set() else "setup", pins=self.pins, label="Hidden gallery PIN",
                      on_done=lambda res: self.toast("PIN saved") if res == "pin_set" else None)
        elif key == "open":
            self.open_app(parts[1], from_voice=True)
        elif key == "back":
            self.back()
        elif key == "home":
            self.go_robot()
        elif key == "mctl":
            self._media_ctl(parts[1], parts[2] if len(parts) > 2 else None)
        elif key == "album":
            n = self.mlib.create_album(":".join(parts[1:]))
            self.toast("Album '%s' created" % n if n else "Invalid name")
        elif key == "record":
            if parts[1] == "start":
                if self.state != "camera":
                    self.open("camera", mode="video")
                self.screens["camera"].mode = "video"
                if not self.camera.recording:
                    self.toggle_recording()
            else:
                if self.camera.recording:
                    self.toggle_recording()
        elif key == "security":
            self.sec.set_enabled(parts[1] == "on")
            self.toast("Security mode %s" % parts[1].upper())
        elif key == "alarm":
            self.sec.siren.stop()
            self.intruder = None
        elif key == "pdf":
            path = F.find_pdf(self.cfg, ":".join(parts[1:]))
            if path:
                self.say("Opening %s." % os.path.splitext(os.path.basename(path))[0], "happy")
                self.open("pdf", path=path)
            else:
                self.say("Sorry, I could not find a PDF called %s." % ":".join(parts[1:]), "sad")
        elif key == "pdfctl":
            self._pdf_ctl(parts[1], parts[2] if len(parts) > 2 else None)
        elif key == "usb":
            drives = F.usb_drives(self.cfg)
            if not drives:
                self.say("I cannot find a USB drive. Please plug one in.", "confused")
            elif parts[1] == "backup":
                self.usb_backup(drives[0]["path"])
            else:
                self.usb_eject(drives[0]["path"])

    # ---- opening apps
    def open_app(self, target, from_voice=False):
        perm = OPEN_PERM.get(target, "apps")
        if not self.require(perm):
            return
        if target == "privacy":
            self.require_pin("privacy", lambda: self.open("privacy"))
        elif target == "gallery":
            self.open("gallery", mode="normal")
        elif target == "analysis":
            self.open("analysis")
        elif target == "documents":
            self.open("files", start="docs")
        elif target == "usb":
            if not F.usb_drives(self.cfg):
                self.say("I do not see a USB drive. Plug one in and it will appear here.", "confused")
            self.open("files", start="usb")
        else:
            self.open(target if target != "movies" else "movies")

    def open_setting(self, tag):
        if tag == "privacy":
            self.require_pin("privacy", lambda: self.open("privacy"))
        elif tag == "switch":
            if self.require("system"):
                self.confirm("Switch to Raspberry Pi OS? Luna will close.", lambda: self.do_exit("os"), "Switch")
        else:
            self.open(tag)

    def _recover(self):
        """Called when ANY handler / frame raised. Log the traceback to logs/buddy.log and carry on."""
        log.exception("recovered from an error - Luna keeps running")
        now = time.time()
        self._err_times = [t for t in self._err_times if now - t < 5.0] + [now]
        self.finger_down = self.mini_active = self.menu_down = self.usb_down = False
        try:
            self.toast("Something went wrong - Luna recovered (see logs/buddy.log)", 3.5)
            if len(self._err_times) >= 8:                  # an error storm: drop back to the robot face
                self._err_times = []
                self.go_robot(leave=False)
        except Exception:
            self.state, self.nav = ROBOT, []

    # ---- hidden vault
    def request_hidden(self, replace=False):
        """Open the PIN / password modal; on success open data/hidden/ through VaultManager. Never exits the app."""
        if not self.require("hidden_gallery"):
            return
        self.vault.mount()
        if self.vault.is_unlocked():
            self.open("gallery", mode="hidden")
            return
        self.open("vault", mode="unlock" if self.vault.is_set() else "setup", on_done=self._vault_done)

    def _vault_done(self, res):
        if res in ("unlocked", "pin_set"):
            self.vault.unlock()
            self.open("gallery", mode="hidden")
            return
        self.toast({"cancel": "Vault closed", "failed": "Wrong password", "locked": "Vault is locked for a while"}.get(res, "Vault stayed locked"), 3)
        g = self.screens["gallery"]
        if self.state != "gallery" or g.mode == "hidden":      # graceful fallback: the normal gallery
            self.open("gallery", mode="normal")

    # ---- remote / voice helpers
    def set_security(self, on, source=""):
        self.sec.set_enabled(on)
        self.toast("Security mode %s" % ("ON" if on else "OFF"), 3)
        self.say("Guard mode %s%s." % ("on" if on else "off", (" from %s" % source) if source else ""), "alert" if on else "happy", 3)

    def notify_text(self, text):
        self.sec.notify_text(text)

    def on_telegram_media(self, path):
        self.toast("New media added to Gallery via Telegram", 4.5)
        self.show("joy", 2.0)
        g = self.screens.get("gallery")
        if self.state == "gallery" and g is not None and g.mode == "normal" and not g.viewing:
            g.reload()

    def _switch_action(self, state, phrase):
        cc, on = self.ctrl, state == "on"
        if not cc.nodes:
            self.say("I do not have a switch node yet. Open the Control Center and add an ESP32.", "confused")
            return
        tgt = cc.resolve_phrase(phrase)
        if not tgt:
            self.say("I could not find a switch called %s. You can rename a switch in the Control Center." % phrase, "confused")
            return
        node, sw = tgt
        self.show("thinking", 2.5)

        def done(ok, msg, n, s):
            name = phrase if phrase in ("light", "lights", "lamp", "fan", "tv", "heater") else s["name"].lower()
            if ok:
                self.toast("%s - %s: %s" % (n["name"], s["name"], "ON" if on else "OFF"), 3.5)
                self.say("Okay, the %s is %s." % (name, "on" if on else "off"), "joy" if on else "happy")
            else:
                self.say("Sorry, I could not reach the switch. Is the E S P 32 powered and on Wi-Fi?", "sad")
                self.toast("Switch failed: %s" % msg, 4)
            scr = self.screens.get("control")
            if scr is not None and self.state == "control":
                scr.reload()
        cc.set_switch(node["id"], sw["servo"], on, done)

    def _calendar_action(self, when):
        if when == "upcoming":
            self.say(self.cal.speak_upcoming(), "happy")
        else:
            self.say(self.cal.speak_day(when), "happy")

    def open_security_photos(self):
        self.open("gallery", mode="security")

    def drawings(self):
        d = self.cfg.DRAWINGS_DIR
        os.makedirs(d, exist_ok=True)
        fs = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(".png")]
        return sorted(fs, key=os.path.getmtime, reverse=True)

    def _pdf_ctl(self, cmd, arg):
        scr = self.screens["pdf"]
        if self.state != "pdf":
            if cmd == "read":
                self.say("Which document should I read? Tap a PDF, or say, Luna, read PDF, and its name.", "happy")
                self.open("files", start="docs")
            else:
                self.say("No PDF is open. Say, Luna, read PDF, and the name of the document.", "confused")
            return
        if cmd == "next":
            self.toast("Page %d" % scr.goto(scr.page + 1))
        elif cmd == "prev":
            self.toast("Page %d" % scr.goto(scr.page - 1))
        elif cmd == "page":
            n = int(arg)
            if n > scr.doc.pages:
                self.say("This document has only %d pages." % scr.doc.pages, "confused")
            else:
                self.toast("Page %d" % scr.goto(n))
        elif cmd == "zin":
            scr.zoom(1)
        elif cmd == "zout":
            scr.zoom(-1)
        elif cmd == "read":
            self.speaker.stop_now()
            scr.start_reading()
        elif cmd == "stopread":
            scr.stop_reading()

    def usb_backup(self, path):
        drive = next((d["path"] for d in F.usb_drives(self.cfg) if path and path.startswith(d["path"])), path)
        self.toast("Backing up...", 3)
        self.run_bg(lambda: F.backup_to_usb(self.cfg, drive),
                    lambda n: (self.toast("Backed up %d new file(s) to the USB drive" % (n or 0), 4), self.say("Backup finished. %d new files copied." % (n or 0), "happy")))

    def usb_eject(self, path):
        drive = next((d["path"] for d in F.usb_drives(self.cfg) if path and path.startswith(d["path"])), path)

        def done(res):
            ok, msg = res if res else (False, "Eject failed")
            self.toast(msg, 4)
            if ok:
                self.screens["files"].drive_gone(drive)
                self.usb_present = bool(F.usb_drives(self.cfg))
        self.toast("Syncing and unmounting ...", 5)
        self.run_bg(lambda: safe_eject(drive) if not self.sim else (True, "You can remove the USB drive now"), done)

    def _usb_watch(self):
        known = {d["path"]: d for d in F.usb_drives(self.cfg)}
        while self.running:
            time.sleep(3)
            cur = {d["path"]: d for d in F.usb_drives(self.cfg)}
            for p, d in cur.items():
                if p not in known:
                    self.events.put(("usb", ("in", d)))
            for p in known:
                if p not in cur:
                    self.events.put(("usb", ("out", p)))
            known = cur

    def _usb_event(self, kind, val):
        self.usb_present = True if kind == "in" else bool(F.usb_drives(self.cfg))
        if kind == "in":
            self.toast("USB drive connected: %s" % val["label"], 4)
            if self.state not in (PHOTO, EXITING):
                self.say("I found a USB drive named %s. Say, Luna, open USB, to see its files." % val["label"], "surprised", 5)
        else:
            self.toast("USB drive removed", 3)
            self.screens["files"].drive_gone(val)
            if self.state == "pdf" and self.screens["pdf"].path.startswith(val):
                self.back()

    def import_usb(self):
        songs, vids = import_from_usb(self.cfg)
        msg = "Imported %d song(s) and %d video(s)" % (songs, vids) if songs or vids else "No new files found on a USB drive"
        self.toast(msg, 3.5)
        return msg

    def remember_speaker(self, mac):
        self.btkeeper.remember(mac)

    def bt_keeper_pause(self):
        self.btkeeper.paused = True

    # ---- music + video
    def play_tracks(self, tracks, idx):
        if not tracks:
            return
        if self.video.running():
            self.video.stop()
        if self.shuffle:
            rest = tracks[:idx] + tracks[idx + 1:]
            random.shuffle(rest)
            tracks, idx = [tracks[idx]] + rest, 0
        self.player.play_list(tracks, idx)

    def play_album(self, album, idx=0):
        self.play_tracks(self.mlib.tracks(album), idx)

    def _voice_play(self, act, r):
        kind, _, q = act.partition(":")
        if kind == "music":
            tracks, idx, desc = self.mlib.resolve(None, q)
            if tracks:
                self.play_tracks(tracks, idx)
                self.say("Playing %s." % desc, "joy")
                return
            if desc:
                mv = self.vlib.find(desc, self.store)
                if mv:
                    self.say("Playing the video %s." % self.vlib.title(mv), "joy")
                    self.play_video(mv)
                    return
            self.say("Sorry, I could not find %s in your music." % (desc or "that"), "sad")
        else:
            path = None
            if q == "latest":
                path = self.store.latest(videos=True) or (self.vlib.movies() or [None])[-1]
            elif q:
                path = self.vlib.find(q, self.store)
            else:
                self.open_app("movies", True)
                return
            if path:
                self.say("Playing %s." % self.vlib.title(path), "joy")
                self.play_video(path)
            else:
                self.say("Sorry, I could not find that video.", "sad")

    def _media_ctl(self, cmd, arg):
        vid = self.video.running()
        if cmd == "pause":
            self.video.ctl("set_property", "pause", True) if vid else self.player.pause()
        elif cmd == "resume":
            self.video.ctl("set_property", "pause", False) if vid else self.player.resume()
        elif cmd == "fwd":
            n = int(arg or 10)
            self.video.ctl("seek", n) if vid else self.player.seek(n)
        elif cmd == "back":
            n = int(arg or 10)
            self.video.ctl("seek", -n) if vid else self.player.seek(-n)
        elif cmd == "next" and not vid:
            self.player.next()
        elif cmd == "prev" and not vid:
            self.player.prev()
        elif cmd == "stop":
            if self.state == "pdf" and self.screens["pdf"].reading:
                self.screens["pdf"].stop_reading()
            else:
                self.video.stop() if vid else self.player.stop()
        elif cmd == "shuffle":
            self.shuffle = arg == "on"
            self.toast("Shuffle %s" % arg)
        elif cmd == "loop":
            self.player.set_loop(arg)
            self.toast("Loop: %s" % arg)

    def cycle_loop(self):
        nxt = {"off": "one", "one": "all", "all": "off"}[self.player.status()["loop"]]
        self.player.set_loop(nxt)
        self.toast({"off": "Loop off", "one": "Repeat this song", "all": "Repeat the whole album"}[nxt])

    def play_video(self, path):
        if not self.video.available:
            self.toast("Install mpv to play videos:  sudo apt install mpv", 4)
            return
        self._music_before_video = self.player.status()["playing"]
        if self._music_before_video:
            self.player.pause()
        if self.video.play(path):
            self.open("video", path=path)
        else:
            self.toast("Could not play this video")

    def end_video(self):
        if self._music_before_video:
            self.player.resume()
            self._music_before_video = False
        self.back()

    def toggle_recording(self):
        cam = self.camera
        if cam.recording:
            path = cam.stop_recording()
            self.toast("Video saved to Gallery" if path else "Recording failed")
        else:
            path = self.store.new_video_path()
            if cam.start_recording(path):
                self.toast("Recording...")
            else:
                self.toast("Camera not ready")

    # ---- people actions
    def _people_action(self, act, person):
        key = act.split(":")[0]
        if key == "introduce":
            name = act.split(":", 1)[1]
            threading.Thread(target=self._introduce, args=(name,), daemon=True).start()
            self.say("Okay! Please look at my camera and hold still. I am learning your face.", "thinking", 6)
        elif key == "whoami":
            if person:
                self.say("You are %s, my %s." % (person["name"], self.people.describe(person)), "happy")
            elif self.camera.unknown_visible():
                self.say("I do not know you yet. Say, Luna, my name is, and then your name, to introduce yourself.", "confused")
            else:
                self.say("I cannot see anyone right now.", "confused")
        elif key == "who_visible":
            vis = [(d["name"], d["person"]) for d in self.camera.visible() if d["person"]]
            unk = self.camera.unknown_visible()
            if vis:
                txt = "I can see " + ", ".join("%s, my %s" % (n, self.people.describe(p)) for n, p in vis) + (" and one person I do not know." if unk else ".")
            else:
                txt = "I can see someone, but I do not know them yet." if unk else "I cannot see anyone right now."
            self.say(txt, "happy")
        elif key == "list_people":
            ppl = self.people.people
            if not ppl:
                self.say("I do not know anyone yet. Introduce me to someone!", "happy")
            else:
                segs = ["%s: %s" % (lab, ", ".join(p["name"] for p in self.people.by_tier(t)))
                        for lab, t in (("masters", MASTER), ("priority", PRIORITY), ("least priority", LEAST)) if self.people.by_tier(t)]
                self.say("I know %d people. %s." % (len(ppl), ". ".join(segs)), "happy", 8)

    def _introduce(self, spoken):
        """Voice introduction: capture the face in front of the camera. New people go to 3rd (least) priority;
        the very first person becomes the master (10 photos, guided poses)."""
        name = clean_name(spoken)
        if not name:
            return
        if self.people.get(name):
            self.events.put(("say", ("I already know someone called %s. Change names in Settings, Privacy." % name, "confused")))
            return
        bootstrap = not self.people.has_master() and not self.sec.enabled
        tier = MASTER if bootstrap else LEAST
        n = self.cfg.MASTER_PHOTOS if bootstrap else self.cfg.LEAST_SAMPLES
        from .uiapps import PROMPTS

        def prog(i, total):
            if bootstrap:
                self.events.put(("say", (PROMPTS[i % len(PROMPTS)], None)))
        status, info = self.camera.enroll(name, tier, samples=n, step_s=1.8 if bootstrap else 0.7, progress=prog)
        if status == "ok":
            self.last_enroll = (name, time.time() + 20)
            self.window_until = time.time() + 20
            if self.intruder:
                self.sec.notify_text("Visitor identified as %s at %s" % (name, time.strftime("%H:%M")))
                self.intruder = None
            msg = ("Nice to meet you, %s! I did not have a master yet, so you are now my master. If I got your name wrong, say no." % name) if bootstrap else \
                  ("Nice to meet you, %s! I will remember your face. I have put you in my third priority list. If I got your name wrong, say no." % name)
            self.events.put(("say", (msg, "love")))
        else:
            if self.intruder:
                self.sec.notify_text("Unknown person says their name is %s (face not saved)" % name)
                self.intruder = None
            msg = {"no_face": "I cannot see a face clearly. Please stand in front of my camera and try again.",
                   "known": "I already know this face as %s." % (info or "someone"), "exists": "I already know someone called %s." % name,
                   "full": "That priority level is full.", "no_camera": "My camera is not working, so I cannot learn faces.",
                   "no_model": "My face recognition files are missing. Please run the face model download script."}.get(status, "Sorry, that did not work.")
            self.events.put(("say", (msg, "confused")))

    def _undo_enroll(self):
        name, _ = self.last_enroll
        self.last_enroll = (None, 0.0)
        if name:
            self.people.forget(name, force=True)
            self.awaiting_name_until = time.time() + 25
            self.say("Sorry about that! Please say your name again, slowly.", "sad")

    # ---- manual flows (Settings > Privacy)
    def flow_add_person(self, tier):
        def got_name(text):
            name = clean_name(text or "")
            if not name:
                return
            if self.people.get(name):
                self.toast("%s already exists" % name)
                return
            n = {MASTER: self.cfg.MASTER_PHOTOS, PRIORITY: self.cfg.PRIORITY_MAX_PHOTOS, LEAST: self.cfg.LEAST_SAMPLES}[tier]
            from .screens import GREEN, BLUE
            self.choose("Add %s" % name, [
                ("Take photos with the camera", "%d photos, I will ask you to turn your head" % n, lambda: self.flow_capture(name, tier, n), GREEN),
                ("Choose photos from the gallery", "pick %s photo%s with the person's face" % (("exactly %d" % n) if tier == MASTER else "1 to %d" % self.people.photo_rule(tier)[1], ""),
                 lambda: self.flow_pick(name, tier), BLUE)])
        self.ask_text("Name of the new person", "", got_name, hint="Type the name, then press OK")

    def flow_capture(self, name, tier, n, replace=False, extra=False):
        self.open("capture", name=name, tier=tier, samples=n, replace=replace, extra=extra)

    def flow_pick(self, name, tier, existing=False):
        lo, hi = self.people.photo_rule(tier)
        if existing:
            hi = hi - self.people.photo_count(self.people.get(name))
            lo = 1
        self.open("gallery", mode="pick")
        self.screens["gallery"].set_pick(hi, lambda paths: self._picked(name, tier, paths, existing))

    def _picked(self, name, tier, paths, existing):
        def work():
            feats, jpgs = [], []
            for p in paths:
                r = self.camera.embed_file(p)
                if r:
                    feats.append(r[0])
                    jpgs.append(r[1])
            lo, hi = self.people.photo_rule(tier)
            if not existing and tier == MASTER and len(feats) != hi:
                return "Master needs exactly %d usable face photos (found %d)" % (hi, len(feats))
            if not feats:
                return "No clear face found in those photos"
            try:
                if existing:
                    self.people.add_photos(name, feats, jpgs)
                else:
                    self.people.enroll(name, feats, tier=tier, jpgs=jpgs)
            except ValueError as e:
                return {"photos": "Wrong number of photos for this level", "full": "That level is full", "exists": "Name already used"}.get(str(e), str(e))
            return "%s: %d photo%s saved" % (name, len(feats), "" if len(feats) == 1 else "s")
        self.run_bg(work, lambda m: self.toast(m or "Failed", 4))

    def flow_add_photos(self, name):
        per = self.people.get(name)
        lo, hi = self.people.photo_rule(per["tier"])
        room = hi - self.people.photo_count(per)
        if room <= 0:
            self.toast("Already at the maximum of %d photos" % hi)
            return
        from .screens import BLUE, GREEN
        self.choose("Add photos to %s" % name, [
            ("Take photos with the camera", "%d more photo%s" % (room, "" if room == 1 else "s"), lambda: self.flow_capture(name, per["tier"], room, extra=True), GREEN),
            ("Choose photos from the gallery", "up to %d" % room, lambda: self.flow_pick(name, per["tier"], existing=True), BLUE)])

    # ---- camera events / security
    def _on_arrive(self, name):
        now = time.time()
        if self.state not in (PHOTO, "pin", "vault", EXITING) and not (self.asleep and not self.cfg.WAKE_ON_FACE):
            try:
                if self.cal_service.greet(name):          # birthday / anniversary wish - once per day per person
                    self.last_greet[name] = now
                    return
            except Exception:
                log.exception("birthday greeting failed")
        if self.state in (PHOTO, "pin", EXITING) or now - self.last_greet.get(name, 0) < self.cfg.GREET_COOLDOWN_S:
            return
        if self.asleep and not self.cfg.WAKE_ON_FACE:
            return
        self.last_greet[name] = now
        self.mark_activity()
        p = self.people.get(name)
        extra = " Welcome back." if p and p["tier"] == MASTER else ""
        self.window_until = now + self.cfg.FOLLOWUP_WINDOW_S + 4
        self.say("%s, %s!%s" % (time_greeting(), name, extra), "love" if p and p["tier"] == MASTER else "happy")

    def _on_unknown(self):
        now = time.time()
        if self.sec.enabled:
            if self.intruder is None:
                self.intruder = dict(since=now)
                self.awaiting_name_until = now + self.cfg.INTRUDER_GRACE_S + 60
                self.window_until = now + 60
                self.say("%s! I do not know you. Please tell me your name." % time_greeting(), "alert", 6)
                self.sec.notify_text("Unknown person detected at %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
            return
        if (not self.cfg.ASK_UNKNOWN or not self.camera.recognition or self.state != ROBOT or self.asleep or not self.greeted
                or now - self.last_unknown_ask < self.cfg.UNKNOWN_ASK_COOLDOWN_S):
            return
        self.last_unknown_ask = now
        self.awaiting_name_until = self.window_until = now + 25
        self.mark_activity()
        self.say("%s! I do not think we have met. What is your name?" % time_greeting(), "happy", 5)

    def _siren_gap(self):
        self.awaiting_name_until = time.time() + 9
        self.speaker.say("Intruder alert. State your name now.")

    def _security_tick(self, now):
        sec = self.sec
        if not sec.enabled:
            if self.intruder:
                self.intruder = None
            return
        vis = self.camera.visible(2.5)
        for d in vis:
            person = d["person"]
            if person is None:
                key, label, kind = "unknown", "Unknown", "unknown"
            elif person["tier"] == LEAST:
                key, label, kind = person["name"], person["name"], "visitor"
            else:
                continue
            if sec.due(key):
                path = sec.photo_path(label)
                if self.camera.capture_jpeg(path, "%s  %s" % (label, time.strftime("%Y-%m-%d %H:%M:%S"))):
                    sec.record(path, label, kind)
        if any(d["person"] is None for d in vis):
            self.unknown_last_seen = now
        if self.intruder:
            if not self.intruder.get("named") and not sec.siren.active and now - self.intruder["since"] > self.cfg.INTRUDER_GRACE_S and now - self.unknown_last_seen < 5:
                sec.siren.start()
                sec.notify_text("ALARM: unknown person did not give a name - siren started at %s" % time.strftime("%H:%M:%S"))
            if now - self.unknown_last_seen > self.cfg.INTRUDER_GONE_S:
                sec.siren.stop()
                sec.notify_text("Unknown person has left the camera view")
                self.intruder = None

    # ---- touch pad
    def _on_touch(self, kind):
        log.info("touch: %s", kind)
        if self.state in self.screens:
            if kind == "double":
                self.go_robot()
            return
        if self.state in (PHOTO, IMAGE_TIMED):
            return
        if self.state == ANALYSIS_TIMED:
            self.state = self._ret if self._ret in self.screens else ROBOT
            self.mark_activity()
            return
        was_asleep = self.asleep
        self.mark_activity()
        if kind == "long":
            if was_asleep:
                self.say("%s! I am awake." % time_greeting(), "happy")
            else:
                self.asleep = True
                self.say("Okay, going to sleep. Touch me to wake me up.", "sleepy", 4)
        elif kind == "double":
            self.enter_analysis(speak=True)
        elif was_asleep:
            self.say("Oh! %s!" % time_greeting(), "surprised")
        else:
            emo, line = random.choice([("joy", "Hehe, that tickles!"), ("love", "Aww, I like that!"), ("happy", "Hello there!"),
                                       ("surprised", "Boop!"), ("wink", "Hey, friend!")])
            self.show(emo, 3.0)
            if self.cfg.TOUCH_SPEAKS:
                self.speaker.say(line)

    # ---- transient screens
    def enter_analysis(self, speak=True):
        self.mark_activity()
        if self.state in (ROBOT, *self.screens):
            self._ret = self.state
        self.state = ANALYSIS_TIMED
        self.analysis.restart()
        if speak and self.cfg.SPEAK_ANALYSIS:
            self.speaker.say(self.brain.summary())

    def start_photo(self, kind):
        if not self.camera.available:
            self.say("Sorry, I cannot find my camera.", "sad")
            return
        secs = self.cfg.GROUP_COUNTDOWN_S if kind == "group" else self.cfg.PHOTO_COUNTDOWN_S
        self._ret = self.state if self.state in self.screens else ROBOT
        self.photo = dict(kind=kind, end=time.time() + secs + 0.6, flash=0.0, taken=False, mirror=kind != "picture")
        self.state = PHOTO

    def _photo_tick(self, now):
        ph = self.photo
        if not ph["taken"] and now >= ph["end"]:
            path = self.store.new_photo_path()
            ok = self.camera.capture_jpeg(path)
            ph["taken"], ph["flash"] = True, now + 0.18
            if ok:
                self.last_photo = path
                self.speaker.shutter()
                self.say("Got it! That is a lovely picture.", "joy")
            else:
                self.say("Sorry, my camera did not give me a picture.", "sad")
        elif ph["taken"] and now > ph["flash"]:
            self.state = self._ret if self._ret in self.screens else ROBOT
            self.mark_activity()

    def show_last_image(self):
        path = self.last_photo if self.last_photo and os.path.exists(self.last_photo) else self.store.latest()
        if not path:
            self.say("I do not have any pictures yet. Ask me to take a selfie!", "confused")
            return
        self._ret = self.state if self.state in self.screens else ROBOT
        self.timed_view.open(path, timed=True, seconds=self.cfg.IMAGE_VIEW_SECONDS)
        self.state = IMAGE_TIMED

    def do_exit(self, target):
        if self.state == EXITING:
            return
        log.info("exit to Raspberry Pi OS (%s)", target)
        self.exit_target = target
        self.state = EXITING
        self.exit_deadline = time.time() + 8
        self.speaker.clear()
        self.say("Okay, switching to Raspberry Pi O S." if target == "os" else "Okay, opening calibration on the Raspberry Pi desktop.", "happy", 6)

    # ============================================================ tick
    def _tick(self, dt):
        now = time.time()
        snap = self.snap = self.sensors.snapshot()
        sp = self.speaker.speaking
        if self.prev_speaking and not sp:
            self.window_until = max(self.window_until, now + self.cfg.FOLLOWUP_WINDOW_S)
        self.prev_speaking = sp
        st = self.player.status()
        if st["active"]:
            self.player.duck(sp or self.sec.siren.sounding)

        if self.state == EXITING and ((not self.speaker.busy() and now > self.exit_deadline - 7.2) or now > self.exit_deadline):
            self.running = False
        if self.state == ANALYSIS_TIMED and self.analysis.remaining() <= 0:
            self.state = self._ret if self._ret in self.screens else ROBOT
        if self.state == PHOTO:
            self._photo_tick(now)
        if self.state == IMAGE_TIMED:
            self.timed_view.tick(dt, self.finger_down or self.touch.down)
            if self.timed_view.finished():
                self.state = self._ret if self._ret in self.screens else ROBOT
                self.mark_activity()
        scr = self.screens.get(self.state)
        if scr is not None:
            scr.tick(dt)
            self.last_activity = now
            self.mini.update()
            limit = self.cfg.HIDDEN_IDLE_S if (self.state == "gallery" and scr.mode == "hidden") else 60 if self.state in ("pin", "vault") else 420
            if self.state not in ("video", "capture", "canvas", "camera", "keyboard") and now - self.ui_last > limit:
                log.info("idle - back to robot mode")
                self.go_robot()

        if not self.greeted and now - self.start_time > (1.5 if self.sim else 4.0):
            self.greeted = True
            note = ""
            if not self.sim and self.listener.status == "no voice model":
                note = " My voice model is missing, so I cannot hear you yet."
            person, _ = self.current()
            self.say("%s%s! I am %s, your desk assistant.%s" % (time_greeting(), (", %s" % person["name"]) if person else "", self.cfg.ROBOT_NAME, note), "happy", 5)

        for tm in list(self.timers):
            if now >= tm:
                self.timers.remove(tm)
                self.mark_activity()
                self.say("Time is up! Your timer has finished.", "surprised", 5)

        if snap["gas_alert"]:
            if not self.alert_active:
                self.alert_active = True
                self.mark_activity()
                self.last_alert_voice = now
                self.speaker.clear()
                self.say("Warning! Gas or smoke detected. Please check the room and open a window.", "alert", 8)
                self.enter_analysis(speak=False)
            elif now - self.last_alert_voice > 30:
                self.last_alert_voice = now
                self.say("Warning! Gas or smoke is still detected.", "alert", 5)
        elif self.alert_active:
            self.alert_active = False
            self.say("The air is clearing up. Phew!", "happy", 4)

        t = snap["temperature"]
        for key, cond, line, emo in (("hot", t is not None and t >= self.cfg.HOT_C, "It is getting really hot in here.", "hot"),
                                     ("cold", t is not None and t <= self.cfg.COLD_C, "Brrr, it is quite cold in here.", "cold")):
            if cond and now - self.comment_at.get(key, -1e9) > 600 and not self.asleep and self.greeted:
                self.comment_at[key] = now
                self.say(line, emo, 5)

        self._security_tick(now)
        self.cal_service.tick(now)
        self.tgbot.gas_tick(snap, now)
        if self.state == "video":
            self.vault.touch()

        idle = now - self.last_activity
        if idle > self.cfg.SLEEP_AFTER_S and not snap["gas_alert"] and self.state == ROBOT and not self.sec.enabled:
            self.asleep = True
        if now > self.next_idle and not self.asleep:
            self.next_idle = now + random.uniform(15, 35)
            self.idle_emotion = random.choices(["happy", "wink", "joy", "neutral"], [4, 2, 1, 1])[0]
            self.idle_until = now + 3.0
        if now > self.idle_until:
            self.idle_emotion = "neutral"

        emo = self._desired_emotion(now, snap, idle)
        for f in (self.face, self.mini.face):
            f.speaking = sp and not self.asleep
            f.set_emotion(emo)
            f.update(dt)

    def _desired_emotion(self, now, snap, idle):
        t = snap["temperature"]
        if self.state == EXITING:
            return "happy"
        if self.asleep:
            return "sleep"
        if snap["gas_alert"] or self.sec.siren.active:
            return "alert"
        if self.thinking:
            return "thinking"
        if self.override and now < self.override_until:
            return self.override
        if now < self.listening_until:
            return "listening"
        if self.sec.enabled:
            return "police"
        if t is not None and t >= self.cfg.HOT_C:
            return "hot"
        if t is not None and t <= self.cfg.COLD_C:
            return "cold"
        if idle > self.cfg.SLEEPY_AFTER_S:
            return "sleepy"
        return self.idle_emotion

    # ============================================================ draw
    def _draw(self):
        st = self.state
        scr = self.screens.get(st)
        if st == ANALYSIS_TIMED:
            self.analysis.draw(self.screen, self.snap)
        elif st == PHOTO:
            ph = self.photo
            left = max(0.0, ph["end"] - time.time())
            num = int(left) + 1 if left > 0.6 and not ph["taken"] else 0
            label = {"group": "Group photo - everyone squeeze in!", "selfie": "Selfie - smile!"}.get(ph["kind"], "Say cheese!")
            draw_photo(self.screen, self.camera.preview_surface(mirror=ph["mirror"]) if not ph["taken"] else None,
                       min(num, 9), ph["taken"] and time.time() < ph["flash"], label, self.size)
        elif st == IMAGE_TIMED:
            self.timed_view.draw(self.screen)
        elif scr is not None:
            scr.draw(self.screen)
            if scr.mini:
                self.mini.draw(self.screen)
        else:
            self.face.draw(self.screen)
            self._draw_ripples()
            if st == ROBOT:
                self._draw_hamburger()
            if self.cfg.SHOW_STATUS_BAR:
                self._status_bar()
        if time.time() < self.toast_until and st != "video":
            u = self.size[1] / 600.0
            img = font(22 * u).render(self.toast_msg, True, (240, 245, 255))
            r = pygame.Rect(int(self.size[0] / 2 - img.get_width() / 2 - 22 * u), int(self.size[1] - 150 * u), int(img.get_width() + 44 * u), int(52 * u))
            pygame.draw.rect(self.screen, (30, 45, 75), r, border_radius=int(26 * u))
            pygame.draw.rect(self.screen, (90, 160, 255), r, width=2, border_radius=int(26 * u))
            self.screen.blit(img, (r.left + 22 * u, r.top + 12 * u))
        self.display.apply_overlay(self.screen)
        if getattr(self, "_shot", None):
            pygame.image.save(self.screen, self._shot)
            self._shot = None

    def screenshot(self, path):
        """Save the next fully drawn frame (used for documentation / testing)."""
        self._shot = path
        for _ in range(60):
            if self._shot is None:
                return True
            time.sleep(0.05)
        return False

    def _draw_hamburger(self):
        r = self.hamburger_rect()
        u = self.size[1] / 600.0
        pygame.draw.rect(self.screen, (16, 26, 46), r, border_radius=int(14 * u))
        pygame.draw.rect(self.screen, (70, 110, 170), r, width=2, border_radius=int(14 * u))
        icon(self.screen, "menu", r.centerx, r.centery, 15 * u, (180, 205, 245))
        if self.usb_present:                                   # lights up while a pen drive is plugged in
            ur = self.usb_rect()
            pygame.draw.rect(self.screen, (14, 46, 36), ur, border_radius=int(14 * u))
            pygame.draw.rect(self.screen, (80, 225, 150), ur, width=3, border_radius=int(14 * u))
            icon(self.screen, "usb", ur.centerx, ur.centery, 15 * u, (120, 255, 180))

    def _draw_ripples(self):
        now = time.time()
        self.ripples = [r for r in self.ripples if now - r[2] < 0.7]
        for x, y, t0 in self.ripples:
            k = (now - t0) / 0.7
            pygame.draw.circle(self.screen, mix((120, 230, 255), (8, 12, 22), k), (int(x), int(y)), int(18 + 70 * k), 4)

    def _status_bar(self):
        w = self.screen.get_width()
        f = font(max(14, self.screen.get_height() // 34), False)
        col = (95, 110, 140)
        left = time.strftime("%H:%M")
        person, _ = self.camera.current_person()
        if person:
            left += "   %s (%s)" % (person["name"], self.people.describe(person))
        st = self.player.status()
        if st["playing"]:
            left += "   Playing: %s" % st["title"][:28]
        self.screen.blit(f.render(left, True, col), (18, 12))
        net = "ONLINE" if self.net.online else "OFFLINE"
        mic = "MIC" if getattr(self.listener, "available", False) else "NO MIC"
        cam = "CAM" if self.camera.available else "NO CAM"
        txt = "%s  |  %s  |  %s  |  %s%s" % (net, self.router.label if not self.sim else "SIM audio", mic, cam, "  |  USB" if self.usb_present else "")
        img = f.render(txt, True, mix(col, (120, 230, 160), 0.6) if self.net.online else col)
        self.screen.blit(img, (w - img.get_width() - 18, 12))
