"""Menu + Settings screens: privacy / people, about, wifi, bluetooth, display, security, telegram."""
import os
import threading
import time

import pygame

from . import commands_help
from .face import font
from .people import LEAST, MASTER, PRIORITY, TIER_LABEL, rank_label
from .screens import (AMBER, BG, BLUE, CARD, GREEN, MUTED, PURPLE, RED, TEXT, TRACK, WHITE, PinPad, button, inside, load_image)
from .ui import ListView, Screen, Slider, icon
from .util import clamp, mix, state_save

TIER_COL = {MASTER: AMBER, PRIORITY: BLUE, LEAST: GREEN}
PROMPTS = ["Look straight at the camera", "Turn slightly to your left", "Turn slightly to your right", "Look up a little", "Look down a little",
           "Smile!", "Tilt your head to the left", "Tilt your head to the right", "Come a little closer", "Move back a little"]


# ----------------------------------------------------------------------------- menu
class MenuScreen(Screen):
    name, title, accent = "menu", "Menu", BLUE
    TILES = [("Settings", "gear", (150, 160, 190), "settings"), ("Gallery", "gallery", BLUE, "gallery"), ("Music", "music", (255, 120, 170), "music"),
             ("Movies", "film", (255, 160, 70), "movies"), ("Documents", "book", (255, 110, 100), "documents"),
             ("Room Analysis", "chart", GREEN, "analysis"), ("Camera", "camera", (120, 210, 255), "camera"),
             ("Drawing", "pencil", (190, 130, 255), "drawing"), ("USB Drive", "usb", (110, 200, 255), "usb"),
             ("Calendar", "calendar", (255, 150, 100), "calendar"), ("Control Center", "control", (80, 210, 190), "control")]
    COLS = 6

    def _tiles(self):
        u, w = self.u, self.w
        cols, gap = self.COLS, 12 * u
        tw = (w - 2 * 24 * u - (cols - 1) * gap) / cols
        th = 190 * u
        out = []
        for i, t in enumerate(self.TILES):
            r, c = divmod(i, cols)
            out.append((t, pygame.Rect(int(24 * u + c * (tw + gap)), int(104 * u + r * (th + gap)), int(tw), int(th))))
        return out

    def draw(self, surf):
        u = self.u
        surf.fill(BG)
        self.topbar(surf, "Menu")
        for (label, ic, col, target), r in self._tiles():
            pygame.draw.rect(surf, mix(CARD, col, 0.16), r, border_radius=int(22 * u))
            pygame.draw.rect(surf, mix(CARD, col, 0.6), r, width=2, border_radius=int(22 * u))
            if target == "usb" and getattr(self.app, "usb_present", False):
                pygame.draw.rect(surf, GREEN, r.inflate(6 * u, 6 * u), width=4, border_radius=int(24 * u))      # lit up: a drive is plugged in
                col = GREEN
            icon(surf, ic, r.centerx, r.centery - 22 * u, 38 * u, col)
            self.text(surf, label, r.centerx, r.bottom - 48 * u, 17 if len(label) > 11 else 20, TEXT, center=True)

    def on_up(self, pos):
        for (label, ic, col, target), r in self._tiles():
            if inside(pos, r):
                self.app.open_app(target)

    def context(self):
        return "The main menu with Settings, Gallery, Music, Movies, Documents, Room Analysis, Camera, Drawing, USB Drive, Calendar and Control Center."

    def comment(self):
        return "You can open the gallery, listen to music, watch movies or draw something. What would you like to do?"


# ----------------------------------------------------------------------------- generic choice list
class ChoiceScreen(Screen):
    name = "choice"

    def enter(self, title="", options=(), accent=BLUE, **kw):
        self.title, self.accent = title, accent
        self.opts = list(options)
        self.lv = ListView(self.u)
        self.lv.set_rows([dict(label=o[0], sub=o[1] if len(o) > 1 else None, tag=i, col=o[3] if len(o) > 3 else accent, icon=o[4] if len(o) > 4 else None)
                          for i, o in enumerate(self.opts)])

    def draw(self, surf):
        u = self.u
        surf.fill(BG)
        self.topbar(surf)
        self.lv.draw(surf, pygame.Rect(int(40 * u), int(100 * u), int(self.w - 80 * u), int(self.h - 120 * u)), self.accent)

    def on_down(self, pos):
        self.lv.down(pos)

    def on_move(self, pos):
        self.lv.move(pos)

    def on_up(self, pos):
        tag = self.lv.up(pos)
        if tag is not None:
            cb = self.opts[tag][2]
            self.app.back()
            if cb:
                cb()


# ----------------------------------------------------------------------------- PIN screen (wraps PinPad)
class PinScreen(Screen):
    name, title = "pin", "PIN"
    has_back = True

    def __init__(self, app):
        super().__init__(app)
        self.pad = PinPad(app.size, app.pins)
        self.on_done = None

    def enter(self, mode="unlock", pins=None, label=None, on_done=None, **kw):
        self.pad.start(mode, pins, label)
        self.on_done = on_done
        self.opened = time.time()

    def draw(self, surf):
        self.pad.draw(surf)
        self.text(surf, "", 0, 0)
        r = self.back_rect()
        button(surf, r, TEXT)
        from .screens import icon_arrow
        icon_arrow(surf, r.centerx, r.centery, 18 * self.u, TEXT, True)

    def priority_hit(self, pos):
        return self.pad.hits_key(pos)

    def on_down(self, pos):
        res = self.pad.tap(pos)
        if res == "cancel":
            self.app.back()
        elif res:
            cb = self.on_done
            self.app.back()
            if cb:
                cb(res)

    def context(self):
        return "A PIN keypad is on the screen. I never look at or say the PIN."


# ----------------------------------------------------------------------------- settings
class SettingsScreen(Screen):
    name, title, accent = "settings", "Settings", (150, 160, 190)

    def enter(self, **kw):
        self.lv = ListView(self.u)
        self.refresh()

    def refresh(self):
        a = self.app
        self.lv.set_rows([
            dict(label="Privacy", sub="Priority levels, people and their photos", icon="lock", tag="privacy", col=AMBER, right="PIN"),
            dict(label="About", sub="Voice commands, Luna and her creator", icon="info", tag="about", col=BLUE),
            dict(label="Wi-Fi", sub="Networks and connection", icon="wifi", tag="wifi", col=GREEN, right=a.wifi_status),
            dict(label="Bluetooth", sub="Speakers and devices", icon="bluetooth", tag="bluetooth", col=(110, 150, 255), right=a.bt_status),
            dict(label="Display", sub="Brightness and volume", icon="sun", tag="display", col=(255, 210, 90)),
            dict(label="Security", sub="Home security mode, Telegram alerts", icon="shield", tag="security", col=RED, right="ON" if a.sec.enabled else "OFF",
                 rcol=RED if a.sec.enabled else MUTED),
            dict(label="Switch to Raspberry Pi OS", sub="Close Luna and show the desktop", icon="power", tag="switch", col=(190, 130, 255)),
        ], keep=True)

    def draw(self, surf):
        u = self.u
        surf.fill(BG)
        self.topbar(surf)
        self.refresh()
        self.lv.draw(surf, pygame.Rect(int(40 * u), int(98 * u), int(self.w - 80 * u), int(self.h - 110 * u)), BLUE)

    def on_down(self, pos):
        self.lv.down(pos)

    def on_move(self, pos):
        self.lv.move(pos)

    def on_up(self, pos):
        tag = self.lv.up(pos)
        if tag:
            self.app.open_setting(tag)

    def context(self):
        return "The Settings list: Privacy, About, Wi-Fi, Bluetooth, Display, Security and Switch to Raspberry Pi OS."

    def comment(self):
        return "This is where you manage people, Wi-Fi, Bluetooth, brightness and security. Tell me which one you would like to open."


# ----------------------------------------------------------------------------- privacy: people
class PrivacyScreen(Screen):
    name, title, accent = "privacy", "Privacy - people and priority", AMBER

    def enter(self, tier=MASTER, **kw):
        self.tier = tier if isinstance(tier, str) else MASTER
        self.lv = ListView(self.u)
        self.pic_cache = {}
        self._rows()

    def _tabs(self):
        u = self.u
        w3 = (self.w - 80 * u - 2 * 14 * u) / 3
        return [(t, pygame.Rect(int(40 * u + i * (w3 + 14 * u)), int(92 * u), int(w3), int(58 * u))) for i, t in enumerate((MASTER, PRIORITY, LEAST))]

    def _add_rect(self):
        u = self.u
        return pygame.Rect(int(40 * u), int(self.h - 74 * u), int(self.w - 80 * u), int(60 * u))

    def _pin_rect(self):
        u = self.u
        return pygame.Rect(int(self.w - 40 * u - 170 * u), int(12 * u), int(170 * u), int(54 * u))

    def _rows(self):
        p = self.app.people
        rows = []
        for person in p.by_tier(self.tier):
            lo, hi = p.photo_rule(self.tier)
            n = p.photo_count(person)
            ok = lo <= n <= hi
            rows.append(dict(label=person["name"], sub="%d photo%s%s" % (n, "" if n == 1 else "s", "" if ok else "  -  needs %d" % lo),
                             icon="user", tag=person["name"], col=TIER_COL[self.tier] if ok else RED,
                             right="since " + person.get("added", "")[:10]))
        self.lv.set_rows(rows, keep=True)

    def draw(self, surf):
        u, p = self.u, self.app.people
        surf.fill(BG)
        self.topbar(surf)
        self._rows()
        for t, r in self._tabs():
            mx = p.max_people(t)
            n = len(p.by_tier(t))
            col = TIER_COL[t]
            sel = t == self.tier
            pygame.draw.rect(surf, mix(CARD, col, 0.35 if sel else 0.08), r, border_radius=int(14 * u))
            pygame.draw.rect(surf, col if sel else mix(CARD, col, 0.4), r, width=3 if sel else 2, border_radius=int(14 * u))
            lab = {MASTER: "1st  Master", PRIORITY: "2nd  Priority", LEAST: "3rd  Least"}[t]
            self.text(surf, lab, r.centerx, r.top + 7 * u, 19, TEXT, center=True)
            self.text(surf, "%d / %s" % (n, mx if mx else "no limit"), r.centerx, r.top + 31 * u, 16, MUTED, False, center=True)
        lo, hi = p.photo_rule(self.tier)
        rule = {MASTER: "Master: up to %d people, exactly %d photos each" % (p.max_people(MASTER), lo),
                PRIORITY: "Priority: up to %d people, up to %d photos each (set manually)" % (p.max_people(PRIORITY), hi),
                LEAST: "Least priority: unlimited people. New people introduced to Luna start here."}[self.tier]
        self.text(surf, rule, self.w / 2, 156 * u, 17, MUTED, False, center=True)
        area = pygame.Rect(int(40 * u), int(184 * u), int(self.w - 80 * u), int(self.h - 276 * u))
        self.lv.draw(surf, area, TIER_COL[self.tier])
        if not self.lv.rows:
            self.text(surf, "Nobody here yet", self.w / 2, 280 * u, 26, MUTED, center=True)
        add = self._add_rect()
        room = p.has_room(self.tier)
        button(surf, add, GREEN if room else MUTED, mix(CARD, GREEN, 0.35) if room else None)
        self.text(surf, "+  Add person" if room else "This level is full", add.centerx, add.centery - 12 * u, 22, TEXT, center=True)
        pr = self._pin_rect()
        button(surf, pr, MUTED)
        self.text(surf, "Change PIN", pr.centerx, pr.centery - 11 * u, 20, TEXT, center=True)

    def on_down(self, pos):
        if pos[1] > 184 * self.u and pos[1] < self.h - 90 * self.u:
            self.lv.down(pos)

    def on_move(self, pos):
        self.lv.move(pos)

    def on_up(self, pos):
        for t, r in self._tabs():
            if inside(pos, r):
                self.tier = t
                self.lv.scroll = 0
                return
        if inside(pos, self._add_rect()):
            if self.app.people.has_room(self.tier):
                self.app.flow_add_person(self.tier)
            return
        if inside(pos, self._pin_rect()):
            self.app.open("pin", mode="change", pins=self.app.ppins, label="Privacy PIN",
                          on_done=lambda r: self.app.toast("Privacy PIN changed") if r == "pin_set" else None)
            return
        tag = self.lv.up(pos)
        if tag:
            self.app.open("person", name=tag)

    def context(self):
        p = self.app.people
        return "Privacy settings listing %d masters, %d priority people and %d least-priority people." % (
            len(p.by_tier(MASTER)), len(p.by_tier(PRIORITY)), len(p.by_tier(LEAST)))

    def comment(self):
        p = self.app.people
        if not p.has_master():
            return "You have no master yet. Add yourself first with ten photos from different angles."
        return "Masters are fully trusted, priority people get most features, and newly introduced people start at least priority."


class PersonScreen(Screen):
    name, accent = "person", AMBER

    def enter(self, name="", **kw):
        self.pname = name
        self.title = name
        self.remove_mode = False
        self.cache = {}

    def person(self):
        return self.app.people.get(self.pname)

    def _btns(self):
        u = self.u
        x, w = self.w - 270 * u, 240 * u
        names = ["rename", "move", "retake", "add", "remove", "delete"]
        return {n: pygame.Rect(int(x), int(100 * u + i * 70 * u), int(w), int(58 * u)) for i, n in enumerate(names)}

    def draw(self, surf):
        u, p = self.u, self.app.people
        per = self.person()
        surf.fill(BG)
        self.topbar(surf, self.pname)
        if not per:
            self.app.back()
            return
        col = TIER_COL[per["tier"]]
        lo, hi = p.photo_rule(per["tier"])
        n = p.photo_count(per)
        self.text(surf, "%s  -  %d photo%s" % (TIER_LABEL[per["tier"]], n, "" if n == 1 else "s"), 40 * u, 96 * u, 22, col)
        self.text(surf, "Allowed: %s photos" % (("exactly %d" % lo) if lo == hi else "%d to %d" % (lo, hi)), 40 * u, 128 * u, 17, MUTED, False)
        cols = 4
        tw = (self.w - 340 * u - 40 * u - (cols - 1) * 12 * u) / cols
        th = tw
        for i in range(n):
            r, c = divmod(i, cols)
            rect = pygame.Rect(int(40 * u + c * (tw + 12 * u)), int(164 * u + r * (th + 12 * u)), int(tw), int(th))
            path = p.photo_file(per, i)
            img = None
            if path and os.path.exists(path):
                img = self.cache.get(path) or load_image(path)
                if img is not None:
                    self.cache[path] = img
                    iw, ih = img.get_size()
                    k = max(tw / iw, th / ih)
                    big = pygame.transform.smoothscale(img, (max(1, int(iw * k)), max(1, int(ih * k))))
                    tile = pygame.Surface((int(tw), int(th)))
                    tile.blit(big, ((int(tw) - big.get_width()) // 2, (int(th) - big.get_height()) // 2))
                    surf.blit(tile, rect.topleft)
            if img is None:
                pygame.draw.rect(surf, CARD, rect)
                icon(surf, "user", rect.centerx, rect.centery, 26 * u, MUTED)
            pygame.draw.rect(surf, RED if self.remove_mode else mix(CARD, col, 0.5), rect, width=3, border_radius=4)
            if self.remove_mode:
                icon(surf, "x", rect.right - 20 * u, rect.top + 20 * u, 12 * u, RED)
        labels = {"rename": ("Rename", "gear", BLUE), "move": ("Change level", "shield", AMBER), "retake": ("Retake all photos", "camera", GREEN),
                  "add": ("Add photos", "plus", GREEN), "remove": ("Done removing" if self.remove_mode else "Remove photos", "x", MUTED), "delete": ("Delete person", "trash", RED)}
        for k, r in self._btns().items():
            lab, ic, c = labels[k]
            disabled = (k == "add" and n >= hi) or (k == "remove" and n <= lo and not self.remove_mode)
            button(surf, r, MUTED if disabled else c)
            icon(surf, ic, r.left + 34 * u, r.centery, 14 * u, MUTED if disabled else c)
            self.text(surf, lab, r.left + 64 * u, r.centery - 11 * u, 19, MUTED if disabled else TEXT)

    def on_up(self, pos):
        per, p = self.person(), self.app.people
        if not per:
            return
        lo, hi = p.photo_rule(per["tier"])
        n = p.photo_count(per)
        for k, r in self._btns().items():
            if not inside(pos, r):
                continue
            if k == "rename":
                self.app.ask_text("Rename %s" % self.pname, self.pname, self._rename)
            elif k == "move":
                opts = []
                for t in (MASTER, PRIORITY, LEAST):
                    if t != per["tier"]:
                        ok, msg = p.can_move(self.pname, t)
                        opts.append((TIER_LABEL[t], msg or "Move %s here" % self.pname, (lambda t=t: self._move(t)), TIER_COL[t]))
                self.app.choose("Move %s to..." % self.pname, opts, AMBER)
            elif k == "retake":
                self.app.flow_capture(self.pname, per["tier"], p.target_samples(per["tier"]) if per["tier"] != LEAST else self.app.cfg.LEAST_SAMPLES, replace=True)
            elif k == "add":
                if n < hi:
                    self.app.flow_add_photos(self.pname)
            elif k == "remove":
                self.remove_mode = not self.remove_mode
            elif k == "delete":
                self.app.confirm("Delete %s and all their photos?" % self.pname, self._delete, "Delete", danger=True)
            return
        if self.remove_mode:
            u = self.u
            cols = 4
            tw = (self.w - 340 * u - 40 * u - (cols - 1) * 12 * u) / cols
            for i in range(n):
                r, c = divmod(i, cols)
                rect = pygame.Rect(int(40 * u + c * (tw + 12 * u)), int(164 * u + r * (tw + 12 * u)), int(tw), int(tw))
                if inside(pos, rect):
                    try:
                        p.remove_photo(self.pname, i)
                    except ValueError:
                        self.app.toast("%s needs at least %d photos" % (TIER_LABEL[per["tier"]].split(" ")[0], lo))
                    return

    def _rename(self, text):
        if text and text.strip():
            if self.app.people.rename(self.pname, text):
                self.pname = self.title = self.app.people.find(text)["name"]
                self.app.toast("Renamed to %s" % self.pname)
            else:
                self.app.toast("That name is already used")

    def _move(self, tier):
        try:
            self.app.people.set_tier(self.pname, tier)
            self.app.toast("%s is now %s" % (self.pname, TIER_LABEL[tier]))
        except ValueError as e:
            self.app.toast(str(e))

    def _delete(self):
        try:
            self.app.people.forget(self.pname)
            self.app.toast("%s deleted" % self.pname)
        except ValueError:
            self.app.toast("You cannot delete the only master")

    def context(self):
        return "The privacy page for %s, who is %s, with their face photos." % (self.pname, self.person()["tier"] if self.person() else "unknown")


class CaptureScreen(Screen):
    """Camera view while Luna learns a face (guided poses)."""
    name, title, accent = "capture", "Learning a face", GREEN
    has_back = True

    def enter(self, name="", tier=LEAST, samples=3, replace=False, extra=False, **kw):
        self.pname, self.tier, self.n, self.replace, self.extra = name, tier, samples, replace, extra
        self.title = "Photos of %s" % name
        self.done_i, self.status, self.msg, self.finished, self._said = 0, None, "", False, -1
        self.cancelled = False
        threading.Thread(target=self._run, daemon=True).start()

    def _progress(self, i, n):
        self.done_i = i + 1
        if i != self._said:
            self._said = i
            self.app.speaker.say(PROMPTS[i % len(PROMPTS)]) if (self.n >= 5 and i % 2 == 0) else None

    def _run(self):
        cam = self.app.camera
        step = 1.8 if self.n >= 5 else 0.7
        if self.extra:
            st, info = cam.add_samples(self.pname, self.n, step, self._progress)
        else:
            st, info = cam.enroll(self.pname, self.tier, samples=self.n, step_s=step, progress=self._progress, replace=self.replace)
        self.status, self.finished = st, True
        self.msg = {"ok": "Done! %d photos saved." % self.n, "no_face": "I could not see your face clearly. Try again.",
                    "known": "This face already belongs to %s." % info, "no_camera": "No camera found.", "no_model": "Face models are missing.",
                    "photos": "Wrong number of photos.", "full": "That level is full.", "exists": "That name already exists."}.get(st, "Failed: %s" % st)

    def on_back(self):
        self.cancelled = True
        self.app.back()

    def tick(self, dt):
        if self.finished and not self.cancelled:
            self.cancelled = True
            self.app.toast(self.msg, 3.5)
            self.app.speaker.say(self.msg)
            self.app.back()

    def draw(self, surf):
        u, w, h = self.u, self.w, self.h
        surf.fill((0, 0, 0))
        pv = self.app.camera.preview_surface(mirror=True)
        if pv is not None:
            iw, ih = pv.get_size()
            k = min((w) / iw, (h - 100 * u) / ih)
            surf.blit(pygame.transform.smoothscale(pv, (int(iw * k), int(ih * k))), ((w - int(iw * k)) // 2, int(80 * u)))
        self.topbar(surf, self.title)
        prompt = PROMPTS[max(0, self.done_i - 1) % len(PROMPTS)] if self.n >= 5 else "Look at the camera"
        pygame.draw.rect(surf, (0, 0, 0), pygame.Rect(0, int(h - 100 * u), w, int(100 * u)))
        self.text(surf, prompt, w / 2, h - 90 * u, 30, TEXT, center=True)
        bar = pygame.Rect(int(80 * u), int(h - 36 * u), int(w - 160 * u), int(14 * u))
        pygame.draw.rect(surf, TRACK, bar, border_radius=7)
        fw = int(bar.width * min(1.0, self.done_i / float(max(1, self.n))))
        if fw > 2:
            pygame.draw.rect(surf, GREEN, pygame.Rect(bar.left, bar.top, fw, bar.height), border_radius=min(7, fw // 2))
        self.text(surf, "Photo %d of %d" % (min(self.done_i, self.n), self.n), w / 2, h - 58 * u, 18, MUTED, False, center=True)

    def context(self):
        return "The camera is learning the face of %s, photo %d of %d." % (self.pname, self.done_i, self.n)


# ----------------------------------------------------------------------------- about
class AboutScreen(Screen):
    name, title, accent = "about", "About Luna", BLUE

    def enter(self, **kw):
        self.scroll, self.down_pos, self.last, self.moved = 0.0, None, None, 0.0
        self.lines = self._build()

    def _wrap(self, text, size, maxw):
        f = font(size * self.u, False)
        out, line = [], ""
        for wd in text.split():
            t = (line + " " + wd).strip()
            if f.render(t, True, TEXT).get_width() > maxw:
                out.append(line)
                line = wd
            else:
                line = t
        out.append(line)
        return out

    def _build(self):
        c, a = self.app.cfg, self.app
        maxw = self.w - 100 * self.u
        L = [("h", "Luna - desk assistant pet robot")]
        for t in ["Luna is a friendly desk robot (she is Luna, not WALL-E). She shows feelings on her face, listens and talks (online and offline), "
                  "reacts to touch, recognises faces, watches the room, plays music and movies, takes pictures and videos, and can guard your home.",
                  "Hardware: Raspberry Pi 4 (4 GB), 7 inch HDMI touch display, DHT22 temperature and humidity, MQ-2 gas sensor, TTP223 touch sensor, "
                  "USB microphone, USB webcam, Bluetooth speaker.",
                  "Software: Python, pygame, Vosk offline speech recognition, OpenCV face recognition, mpv media player."]:
            L += [("p", x) for x in self._wrap(t, 19, maxw)] + [("s", "")]
        L.append(("h", "Her creator"))
        y, m, d = c.DEVELOPER_DOB
        from datetime import date
        born = date(y, m, d)
        age = date.today().year - y - ((date.today().month, date.today().day) < (m, d))
        for t in ["%s built Luna." % c.DEVELOPER_NAME,
                  "Born: %s (age %d)." % (born.strftime("%d %B %Y").lstrip("0"), age),
                  "Studying: %s at %s, graduating in %d." % (c.DEVELOPER_COURSE, c.DEVELOPER_COLLEGE, c.DEVELOPER_GRAD_YEAR),
                  "Interests: %s." % c.DEVELOPER_INTERESTS]:
            L += [("p", x) for x in self._wrap(t, 19, maxw)]
        L.append(("s", ""))
        for group, items in commands_help.COMMANDS:
            L.append(("h", "Voice commands - " + group))
            for phrase, what in items:
                L.append(("c", phrase))
                L += [("p", x) for x in self._wrap(what, 17, maxw - 20 * self.u)]
            L.append(("s", ""))
        return L

    def _height(self):
        return sum({"h": 44, "c": 30, "p": 26, "s": 12}[k] for k, _ in self.lines) * self.u

    def draw(self, surf):
        u = self.u
        surf.fill(BG)
        y = 96 * u - self.scroll
        for kind, txt in self.lines:
            hgt = {"h": 44, "c": 30, "p": 26, "s": 12}[kind] * u
            if y + hgt > 80 * u and y < self.h:
                if kind == "h":
                    self.text(surf, txt, 40 * u, y + 6 * u, 24, BLUE)
                elif kind == "c":
                    self.text(surf, "\u201c%s\u201d" % txt, 50 * u, y + 2 * u, 18, GREEN)
                elif kind == "p":
                    self.text(surf, txt, 60 * u if self.lines and False else 50 * u, y + 2 * u, 17, TEXT, False)
            y += hgt
        self.topbar(surf)

    def _max(self):
        return max(0.0, self._height() - (self.h - 110 * self.u))

    def on_down(self, pos):
        self.down_pos = self.last = pos

    def on_move(self, pos):
        if self.down_pos:
            self.scroll = clamp(self.scroll - (pos[1] - self.last[1]), 0, self._max())
            self.last = pos

    def on_up(self, pos):
        self.down_pos = None

    def context(self):
        return "The About page: information about Luna, her creator Koushik, and the list of voice commands."

    def comment(self):
        return "You can scroll to see every voice command I understand. Try saying, Luna, play a god song."


# ----------------------------------------------------------------------------- wifi / bluetooth
class WifiScreen(Screen):
    name, title, accent = "wifi", "Wi-Fi", GREEN

    def enter(self, **kw):
        self.lv = ListView(self.u)
        self.nets, self.busy, self.msg = [], False, ""
        self.rescan()

    def _btn(self):
        u = self.u
        return pygame.Rect(int(self.w - 190 * u), int(104 * u), int(150 * u), int(54 * u))

    def rescan(self):
        if self.busy:
            return
        self.busy, self.msg = True, "Scanning..."
        self.app.run_bg(self.app.wifi.scan, self._got)

    def _got(self, nets):
        self.busy, self.msg = False, "" if nets else "No networks found (is Wi-Fi on?)"
        self.nets = nets or []
        act = next((n["ssid"] for n in self.nets if n["active"]), None)
        self.app.wifi_status = act or "not connected"
        self.lv.set_rows([dict(label=n["ssid"], sub="Connected" if n["active"] else ("Saved" if n["saved"] else ("Secured" if n["secure"] else "Open")),
                               icon="wifi", tag=n["ssid"], col=GREEN if n["active"] else BLUE, hl=n["active"],
                               right="%d%%%s" % (n["signal"], "  (locked)" if n["secure"] else "")) for n in self.nets])

    def draw(self, surf):
        u = self.u
        surf.fill(BG)
        self.topbar(surf)
        act = self.app.wifi_status
        self.text(surf, "Connected to:  %s" % act, 40 * u, 100 * u, 22, GREEN if act != "not connected" else MUTED)
        self.text(surf, self.msg or "Tap a network to connect", 40 * u, 134 * u, 17, AMBER if self.busy else MUTED, False)
        b = self._btn()
        button(surf, b, BLUE)
        icon(surf, "refresh", b.left + 34 * u, b.centery, 14 * u, BLUE)
        self.text(surf, "Rescan", b.left + 62 * u, b.centery - 11 * u, 19)
        self.lv.draw(surf, pygame.Rect(int(40 * u), int(172 * u), int(self.w - 80 * u), int(self.h - 190 * u)), GREEN)

    def on_down(self, pos):
        self.lv.down(pos)

    def on_move(self, pos):
        self.lv.move(pos)

    def on_up(self, pos):
        if inside(pos, self._btn()):
            self.lv.down_pos = None
            self.rescan()
            return
        tag = self.lv.up(pos)
        net = next((n for n in self.nets if n["ssid"] == tag), None)
        if not net or self.busy:
            return
        if net["active"]:
            self.app.choose(net["ssid"], [("Disconnect", "Leave this network", lambda: self._do(self.app.wifi.disconnect, "Disconnected"), RED),
                                          ("Forget network", "Remove the saved password", lambda: self._do(lambda: self.app.wifi.forget(net["ssid"]), "Forgotten"), AMBER)], GREEN)
        elif net["saved"] or not net["secure"]:
            self._connect(net["ssid"], None)
        else:
            self.app.ask_text("Password for %s" % net["ssid"], "", lambda pw: self._connect(net["ssid"], pw) if pw else None, password=True)

    def _connect(self, ssid, pw):
        self.busy, self.msg = True, "Connecting to %s..." % ssid
        self.app.run_bg(lambda: self.app.wifi.connect(ssid, pw), self._connected)

    def _connected(self, res):
        ok, msg = res if res else (False, "Failed")
        self.app.toast(msg, 3)
        self.busy = False
        self.rescan()

    def _do(self, fn, ok_msg):
        self.app.run_bg(fn, lambda r: (self.app.toast(ok_msg if r else "Failed"), self.rescan()))

    def context(self):
        return "The Wi-Fi page showing %d networks; connected to %s." % (len(self.nets), self.app.wifi_status)


class BluetoothScreen(Screen):
    name, title, accent = "bluetooth", "Bluetooth", (110, 150, 255)

    def enter(self, **kw):
        self.lv = ListView(self.u)
        self.devs, self.busy, self.msg = [], False, ""
        self.refresh(False)

    def _btn(self):
        u = self.u
        return pygame.Rect(int(self.w - 210 * u), int(104 * u), int(170 * u), int(54 * u))

    def refresh(self, scan):
        if self.busy:
            return
        self.busy, self.msg = True, "Searching for devices..." if scan else "Loading..."
        self.app.run_bg(lambda: self.app.bt.devices(scan), self._got)

    def _got(self, devs):
        self.busy, self.devs = False, devs or []
        self.msg = "" if self.devs else "No devices yet - put your speaker in pairing mode and tap Scan"
        con = [d["name"] for d in self.devs if d["connected"]]
        self.app.bt_status = ", ".join(con) if con else "not connected"
        self.lv.set_rows([dict(label=d["name"], sub="Connected" if d["connected"] else ("Paired" if d["paired"] else "Available - tap to pair"),
                               icon="bluetooth", tag=d["mac"], col=GREEN if d["connected"] else (110, 150, 255), hl=d["connected"],
                               right="connected" if d["connected"] else "") for d in self.devs], keep=True)

    def draw(self, surf):
        u = self.u
        surf.fill(BG)
        self.topbar(surf)
        self.text(surf, "Connected:  %s" % self.app.bt_status, 40 * u, 100 * u, 22, GREEN if self.app.bt_status != "not connected" else MUTED)
        self.text(surf, self.msg or "Tap a device to connect or disconnect", 40 * u, 134 * u, 17, AMBER if self.busy else MUTED, False)
        b = self._btn()
        button(surf, b, BLUE)
        icon(surf, "refresh", b.left + 34 * u, b.centery, 14 * u, BLUE)
        self.text(surf, "Scan for new", b.left + 62 * u, b.centery - 11 * u, 18)
        self.lv.draw(surf, pygame.Rect(int(40 * u), int(172 * u), int(self.w - 80 * u), int(self.h - 190 * u)), BLUE)

    def on_down(self, pos):
        self.lv.down(pos)

    def on_move(self, pos):
        self.lv.move(pos)

    def on_up(self, pos):
        if inside(pos, self._btn()):
            self.lv.down_pos = None
            self.refresh(True)
            return
        tag = self.lv.up(pos)
        d = next((x for x in self.devs if x["mac"] == tag), None)
        if not d or self.busy:
            return
        if d["connected"]:
            opts = [("Disconnect", "Stay paired but disconnect", lambda: self._act("disconnect", d), RED),
                    ("Remove device", "Forget this device", lambda: self._act("remove", d), AMBER)]
        elif d["paired"]:
            opts = [("Connect", "Use this device", lambda: self._act("connect", d), GREEN),
                    ("Remove device", "Forget this device", lambda: self._act("remove", d), AMBER)]
        else:
            opts = [("Pair and connect", "First time with this device", lambda: self._act("connect", d), GREEN)]
        self.app.choose(d["name"], opts, BLUE)

    def _act(self, what, d):
        self.busy, self.msg = True, "%s %s..." % (what.title(), d["name"])
        fn = {"connect": self.app.bt.connect, "disconnect": self.app.bt.disconnect, "remove": self.app.bt.remove}[what]

        def done(res):
            ok = res[0] if isinstance(res, tuple) else res
            self.app.toast("%s: %s" % (d["name"], what + ("ed" if what == "connect" and ok else " done" if ok else " failed")), 3)
            if what == "connect" and ok:
                self.app.remember_speaker(d["mac"])
            if what == "disconnect" and ok:
                self.app.bt_keeper_pause()
            self.busy = False
            self.refresh(False)
        self.app.run_bg(lambda: fn(d["mac"]), done)

    def context(self):
        return "The Bluetooth page. Connected device: %s." % self.app.bt_status


# ----------------------------------------------------------------------------- display
class DisplayScreen(Screen):
    name, title, accent = "display", "Display and sound", (255, 210, 90)

    def enter(self, **kw):
        self.sb, self.sv = Slider(self.u), Slider(self.u)
        self.sb.value = (self.app.display.level - 10) / 90.0
        self.sv.value = (self.app.router.volume - 20) / 80.0

    def draw(self, surf):
        u = self.u
        surf.fill(BG)
        self.topbar(surf)
        for i, (lab, sl, val, ic, col, sub) in enumerate([
                ("Brightness", self.sb, "%d%%" % self.app.display.level, "sun", (255, 210, 90), self.app.display.describe()),
                ("Volume", self.sv, "%d%%" % self.app.router.volume, "music", (120, 200, 255), "Speaker volume (Bluetooth or USB)")]):
            y = 120 * u + i * 190 * u
            card = pygame.Rect(int(40 * u), int(y), int(self.w - 80 * u), int(160 * u))
            pygame.draw.rect(surf, CARD, card, border_radius=int(18 * u))
            pygame.draw.rect(surf, mix(CARD, col, 0.5), card, width=2, border_radius=int(18 * u))
            icon(surf, ic, card.left + 50 * u, card.top + 42 * u, 20 * u, col)
            self.text(surf, lab, card.left + 90 * u, card.top + 22 * u, 26, TEXT)
            self.text(surf, val, card.right - 110 * u, card.top + 22 * u, 26, col)
            self.text(surf, sub, card.left + 90 * u, card.top + 58 * u, 15, MUTED, False)
            sl.draw(surf, pygame.Rect(int(card.left + 50 * u), int(card.top + 112 * u), int(card.width - 100 * u), int(30 * u)), col)

    def _apply(self):
        self.app.display.set(10 + self.sb.value * 90)
        self.app.router.volume = int(20 + self.sv.value * 80)
        self.app.router._vol_applied = None
        state_save(self.app.cfg, brightness=self.app.display.level, volume=self.app.router.volume)

    def on_down(self, pos):
        if self.sb.down(pos) is not None or self.sv.down(pos) is not None:
            self._apply()

    def on_move(self, pos):
        if self.sb.drag or self.sv.drag:
            self.sb.move(pos)
            self.sv.move(pos)
            self._apply()

    def on_up(self, pos):
        if self.sb.up(pos) or self.sv.up(pos):
            self._apply()
            self.app.router.refresh() if not self.app.sim else None

    def context(self):
        return "The Display page with brightness %d%% and volume %d%%." % (self.app.display.level, self.app.router.volume)


# ----------------------------------------------------------------------------- security
class SecurityScreen(Screen):
    name, title, accent = "security", "Security mode", RED

    def enter(self, **kw):
        self.lv = ListView(self.u)

    def _toggle(self):
        u = self.u
        return pygame.Rect(int(self.w - 250 * u), int(104 * u), int(200 * u), int(84 * u))

    def draw(self, surf):
        u, s = self.u, self.app.sec
        surf.fill(BG)
        self.topbar(surf)
        card = pygame.Rect(int(40 * u), int(100 * u), int(self.w - 80 * u), int(100 * u))
        pygame.draw.rect(surf, mix(CARD, RED if s.enabled else MUTED, 0.14), card, border_radius=int(18 * u))
        pygame.draw.rect(surf, RED if s.enabled else mix(CARD, MUTED, 0.5), card, width=2, border_radius=int(18 * u))
        icon(surf, "shield", card.left + 56 * u, card.centery, 26 * u, RED if s.enabled else MUTED)
        self.text(surf, "Home security: %s" % ("ON" if s.enabled else "OFF"), card.left + 110 * u, card.top + 18 * u, 28, RED if s.enabled else TEXT)
        self.text(surf, "Camera watches all the time, photographs new faces, alerts you on Telegram, sirens for unknown people", card.left + 110 * u, card.top + 58 * u, 14, MUTED, False)
        t = self._toggle()
        t.top, t.left = card.top + int(8 * u), card.right - int(190 * u)
        t.width, t.height = int(170 * u), int(84 * u)
        self._trect = t
        pygame.draw.rect(surf, RED if s.enabled else TRACK, t, border_radius=int(42 * u))
        knob = t.right - int(42 * u) if s.enabled else t.left + int(42 * u)
        pygame.draw.circle(surf, WHITE, (knob, t.centery), int(34 * u))
        tg = self.app.sec.telegram
        rows = [dict(label="Telegram alerts", sub="Bot token and chat ID", icon="gear", tag="tg", col=BLUE, right="set up" if tg.configured() else "not set", rcol=GREEN if tg.configured() else AMBER),
                dict(label="Security photos", sub="Everyone the camera caught, with date and time", icon="camera", tag="photos", col=AMBER, right="%d" % len(s.photos())),
                dict(label="Send a test alert", sub="Check that Telegram works", icon="shield", tag="test", col=GREEN)]
        self.lv.set_rows(rows, keep=True)
        pend = s.pending()
        if pend:
            self.text(surf, "%d photo(s) waiting to be sent when internet is back" % pend, 40 * u, 214 * u, 16, AMBER, False)
        self.lv.draw(surf, pygame.Rect(int(40 * u), int(240 * u), int(self.w - 80 * u), int(self.h - 260 * u)), RED)

    def on_down(self, pos):
        if pos[1] > 236 * self.u:
            self.lv.down(pos)

    def on_move(self, pos):
        self.lv.move(pos)

    def on_up(self, pos):
        s = self.app.sec
        if inside(pos, self._trect):
            if s.enabled:
                self.app.require_pin("privacy", lambda: (s.set_enabled(False), self.app.toast("Security mode OFF")))
            else:
                s.set_enabled(True)
                self.app.toast("Security mode ON - Luna is on guard")
                self.app.speaker.say("Security mode is on. I will keep watch.")
            return
        tag = self.lv.up(pos)
        if tag == "tg":
            self.app.open("telegram")
        elif tag == "photos":
            self.app.open_security_photos()
        elif tag == "test":
            if self.app.sim:
                self.app.toast("Test alert sent (simulated)")
            else:
                self.app.run_bg(lambda: s.telegram.send_text("Luna test alert - Telegram is working!"), lambda r: self.app.toast(r[1] if r else "Failed", 3))

    def context(self):
        return "The Security page. Security mode is %s." % ("ON" if self.app.sec.enabled else "OFF")

    def comment(self):
        return "Security mode is on, so I am watching the camera." if self.app.sec.enabled else "Security mode is off. Switch it on when you leave the house."


class TelegramScreen(Screen):
    name, title, accent = "telegram", "Telegram alerts", BLUE

    def _rows(self):
        u = self.u
        return {"token": pygame.Rect(int(40 * u), int(150 * u), int(self.w - 80 * u), int(80 * u)),
                "chat": pygame.Rect(int(40 * u), int(250 * u), int(self.w - 80 * u), int(80 * u)),
                "test": pygame.Rect(int(40 * u), int(360 * u), int((self.w - 100 * u) / 2), int(64 * u)),
                "clear": pygame.Rect(int(60 * u + (self.w - 100 * u) / 2), int(360 * u), int((self.w - 100 * u) / 2), int(64 * u))}

    def draw(self, surf):
        u, t = self.u, self.app.sec.telegram
        surf.fill(BG)
        self.topbar(surf)
        self.text(surf, "Tap a box to type it with the on-screen keyboard", 40 * u, 100 * u, 18, MUTED, False)
        self.text(surf, "Create a bot with @BotFather to get the BOT_TOKEN. Send your bot a message, then get your CHAT_ID (e.g. with @userinfobot).", 40 * u, 124 * u, 13, MUTED, False)
        r = self._rows()
        for key, lab, val in (("token", "BOT_TOKEN", t.masked(t.token)), ("chat", "CHAT_ID", t.chat_id or "not set")):
            pygame.draw.rect(surf, CARD, r[key], border_radius=int(14 * u))
            pygame.draw.rect(surf, BLUE, r[key], width=2, border_radius=int(14 * u))
            self.text(surf, lab, r[key].left + 20 * u, r[key].top + 10 * u, 16, MUTED)
            self.text(surf, val, r[key].left + 20 * u, r[key].top + 36 * u, 26, TEXT)
        button(surf, r["test"], GREEN, mix(CARD, GREEN, 0.3))
        self.text(surf, "Send test message", r["test"].centerx, r["test"].centery - 12 * u, 21, TEXT, center=True)
        button(surf, r["clear"], RED)
        self.text(surf, "Clear details", r["clear"].centerx, r["clear"].centery - 12 * u, 21, TEXT, center=True)
        self.text(surf, "Alerts are sent only when Luna is online; otherwise photos are saved and sent later.", 40 * u, 450 * u, 16, AMBER, False)

    def on_up(self, pos):
        r, t = self._rows(), self.app.sec.telegram
        if inside(pos, r["token"]):
            self.app.ask_text("BOT_TOKEN", t.token, lambda v: (t.save(token=v), self.app.toast("Saved")) if v is not None else None, hint="e.g. 123456789:ABCdef...", maxlen=120)
        elif inside(pos, r["chat"]):
            self.app.ask_text("CHAT_ID", t.chat_id, lambda v: (t.save(chat_id=v), self.app.toast("Saved")) if v is not None else None, hint="digits (can start with -)", maxlen=30)
        elif inside(pos, r["test"]):
            self.app.run_bg(lambda: t.send_text("Luna test alert - Telegram is working!") if not self.app.sim else (True, "Sent (simulated)"),
                            lambda res: self.app.toast(res[1] if res else "Failed", 3))
        elif inside(pos, r["clear"]):
            self.app.confirm("Remove the saved Telegram token and chat ID?", lambda: (t.save(token="", chat_id=""), self.app.toast("Cleared")), "Clear", danger=True)

    def context(self):
        return "The Telegram setup page, %s." % ("configured" if self.app.sec.telegram.configured() else "not configured yet")
