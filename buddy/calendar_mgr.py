"""Calendar: events (birthdays, anniversaries, custom), day-prior reminders at 09:00, face-recognition birthday wishes.

data/calendar.json
    {"events": [{"id": "a1b2c3d4", "kind": "birthday|anniversary|custom", "name": "Rahul", "title": "",
                 "month": 11, "day": 19, "year": null, "yearly": true, "person": "Rahul"}]}

* ``person`` links the event to a profile in data/priority/*.json (masters / priority / least priority).
  The month/day is also mirrored into that profile ("birthday": "11-19") so the link is visible in the people files.
* Reminder: every day from 09:00 Luna checks for events happening TOMORROW, plays a chime and announces
  "Reminder: Tomorrow is Rahul's Birthday!".  If Luna was switched off at 09:00 she catches up until 21:00.
* Greeting: when the camera recognises a person whose birthday / anniversary is TODAY, Luna shows joy / love and says
  "Happy Birthday, Rahul! Wishing you an incredible year ahead!" - once per calendar day per person (kept on disk).
"""
import calendar as pycal
import json
import logging
import math
import os
import struct
import subprocess
import threading
import time
import uuid
import wave
from datetime import date, datetime, timedelta

import pygame

from .face import font
from .screens import AMBER, BG, BLUE, CARD, GREEN, MUTED, PURPLE, RED, TEXT, TRACK, button, icon_arrow, inside
from .ui import Screen, icon
from .util import guarded, mix

log = logging.getLogger("calendar")
KINDS = ("birthday", "anniversary", "custom")
KIND_LABEL = {"birthday": "Birthday", "anniversary": "Anniversary", "custom": "Event"}
KIND_COL = {"birthday": (255, 120, 170), "anniversary": AMBER, "custom": BLUE}


def _atomic_write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


# =============================================================================== store
class CalendarStore:
    def __init__(self, cfg, people=None):
        self.cfg, self.people = cfg, people
        self.lock = threading.RLock()
        self.events = []
        self.load()

    def load(self):
        with self.lock:
            try:
                with open(self.cfg.CALENDAR_FILE) as f:
                    self.events = [e for e in json.load(f).get("events", []) if e.get("kind") in KINDS and e.get("month") and e.get("day")]
            except FileNotFoundError:
                self.events = []
            except Exception as e:
                log.warning("cannot read calendar.json: %s", e)
                self.events = []

    def save(self):
        with self.lock:
            _atomic_write(self.cfg.CALENDAR_FILE, {"events": self.events})

    # ------------------------------------------------------------- editing
    def add(self, kind, month, day, name="", title="", year=None, yearly=None, person=None):
        if kind not in KINDS:
            raise ValueError("bad kind")
        try:
            date(2024, int(month), int(day))             # leap year so 29 Feb is allowed
        except ValueError:
            raise ValueError("bad date")
        if yearly is None:
            yearly = kind != "custom" or year is None
        if not yearly and not year:
            year = date.today().year
        person = person or self._guess_person(name)
        ev = dict(id=uuid.uuid4().hex[:8], kind=kind, name=(name or "").strip()[:30], title=(title or "").strip()[:40],
                  month=int(month), day=int(day), year=int(year) if year else None, yearly=bool(yearly), person=person)
        with self.lock:
            self.events.append(ev)
            self.save()
        self._mirror(ev)
        return ev

    def delete(self, event_id):
        with self.lock:
            ev = next((e for e in self.events if e["id"] == event_id), None)
            if not ev:
                return False
            self.events.remove(ev)
            self.save()
        self._unmirror(ev)
        return True

    def _guess_person(self, name):
        if not (self.people and name):
            return None
        p = self.people.get(name)
        return p["name"] if p else None

    # --- keep data/priority/*.json profile in sync ("link calendar entries directly to person profiles")
    def _mirror(self, ev):
        if not (self.people and ev.get("person") and ev["kind"] in ("birthday", "anniversary")):
            return
        try:
            p = self.people.get(ev["person"])
            if p is not None:
                p[ev["kind"]] = "%02d-%02d" % (ev["month"], ev["day"])
                self.people.save()
        except Exception as e:
            log.warning("profile link failed: %s", e)

    def _unmirror(self, ev):
        if not (self.people and ev.get("person") and ev["kind"] in ("birthday", "anniversary")):
            return
        try:
            p = self.people.get(ev["person"])
            if p is not None and p.get(ev["kind"]) == "%02d-%02d" % (ev["month"], ev["day"]):
                p.pop(ev["kind"], None)
                self.people.save()
        except Exception as e:
            log.warning("profile unlink failed: %s", e)

    # ------------------------------------------------------------- queries
    @staticmethod
    def _matches(ev, d):
        if ev["month"] == d.month and ev["day"] == d.day:
            return ev.get("yearly") or ev.get("year") == d.year
        # 29 Feb events are celebrated on 28 Feb in non-leap years
        if ev["month"] == 2 and ev["day"] == 29 and not pycal.isleap(d.year) and d.month == 2 and d.day == 28:
            return ev.get("yearly") or ev.get("year") == d.year
        return False

    def on(self, d):
        with self.lock:
            return [e for e in self.events if self._matches(e, d)]

    def month_marks(self, year, month):
        """{day: [kinds]} for the month grid."""
        marks = {}
        for day in range(1, pycal.monthrange(year, month)[1] + 1):
            ks = [e["kind"] for e in self.on(date(year, month, day))]
            if ks:
                marks[day] = ks
        return marks

    def upcoming(self, days=30, start=None):
        start = start or date.today()
        out = []
        for i in range(days + 1):
            d = start + timedelta(days=i)
            for e in self.on(d):
                out.append((d, e))
        return out

    def for_person_today(self, name, today=None):
        today = today or date.today()
        n = (name or "").strip().lower()
        res = []
        for e in self.on(today):
            if e["kind"] in ("birthday", "anniversary") and n and n in ((e.get("person") or "").lower(), (e.get("name") or "").lower()):
                res.append(e)
        return res

    # ------------------------------------------------------------- wording
    @staticmethod
    def title_of(ev):
        if ev["kind"] == "custom":
            return ev.get("title") or ev.get("name") or "an event"
        return "%s's %s" % (ev.get("name") or "someone", KIND_LABEL[ev["kind"]])

    def reminder_text(self, ev):
        return "Reminder: Tomorrow is %s!" % self.title_of(ev)

    @staticmethod
    def greeting_text(ev):
        who = ev.get("person") or ev.get("name") or "friend"
        if ev["kind"] == "birthday":
            return "Happy Birthday, %s! Wishing you an incredible year ahead!" % who
        if ev["kind"] == "anniversary":
            return "Happy Anniversary, %s! Wishing you many more happy years together!" % who
        return "Today is special, %s!" % who

    def speak_day(self, when):
        """Text for 'what is on my calendar today / tomorrow'."""
        d = date.today() + timedelta(days=1 if when == "tomorrow" else 0)
        evs = self.on(d)
        if not evs:
            return "You have nothing on the calendar %s." % when
        return "%s: %s." % ("Tomorrow" if when == "tomorrow" else "Today", ", ".join(self.title_of(e) for e in evs))

    def speak_upcoming(self):
        ups = [(d, e) for d, e in self.upcoming(30) if d != date.today()][:3]
        if not ups:
            return "Nothing is coming up in the next thirty days."
        return "Coming up: " + "; ".join("%s on %s" % (self.title_of(e), d.strftime("%d %B").lstrip("0")) for d, e in ups) + "."


# =============================================================================== reminders + greetings
class CalendarService:
    """Runs inside the main loop (call .tick(now) every frame - it is cheap)."""

    def __init__(self, app):
        self.app = app
        self.cfg = app.cfg
        self.store = app.cal
        self.st = self._load()
        self._chime = None

    # --- persistent once-a-day bookkeeping
    def _load(self):
        try:
            with open(self.cfg.CALENDAR_STATE_FILE) as f:
                d = json.load(f)
        except Exception:
            d = {}
        d.setdefault("reminded", "")
        d.setdefault("greeted", [])
        return d

    def _save(self):
        try:
            _atomic_write(self.cfg.CALENDAR_STATE_FILE, self.st)
        except Exception as e:
            log.warning("calendar state: %s", e)

    # --- 09:00 reminder
    def due_reminder(self, now_dt):
        today = now_dt.date().isoformat()
        if self.st["reminded"] == today:
            return False
        start = now_dt.replace(hour=self.cfg.CALENDAR_REMIND_HOUR, minute=self.cfg.CALENDAR_REMIND_MINUTE, second=0, microsecond=0)
        return start <= now_dt < now_dt.replace(hour=self.cfg.CALENDAR_CATCHUP_UNTIL_HOUR, minute=0, second=0, microsecond=0)

    def tick(self, now=None):
        now_dt = datetime.fromtimestamp(now) if now else datetime.now()
        if self.app.state in ("photo", "exiting") or not self.app.greeted:
            return
        if self.due_reminder(now_dt):
            self.st["reminded"] = now_dt.date().isoformat()
            self._save()
            evs = self.store.on(now_dt.date() + timedelta(days=1))
            if evs:
                self.announce([self.store.reminder_text(e) for e in evs])

    def announce(self, lines):
        a = self.app
        a.mark_activity()
        for ln in lines:
            a.notify_text(ln)

        def go():
            self._play_chime()
            for ln in lines:
                a.events.put(("say", (ln, "happy", len(ln) * 0.075 + 3)))
        threading.Thread(target=go, daemon=True).start()

    def _chime_path(self):
        if self._chime:
            return self._chime
        p = os.path.join(self.cfg.DATA_DIR, "chime.wav")
        if not os.path.exists(p):
            os.makedirs(self.cfg.DATA_DIR, exist_ok=True)
            rate = 22050
            with wave.open(p, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                frames = bytearray()
                for f0, dur in ((880.0, 0.22), (1175.0, 0.22), (1568.0, 0.45)):
                    n = int(rate * dur)
                    for i in range(n):
                        env = min(1.0, i / 300.0) * math.exp(-3.0 * i / n)
                        frames += struct.pack("<h", int(math.sin(2 * math.pi * f0 * i / rate) * 0.5 * 32000 * env))
                w.writeframes(bytes(frames))
        self._chime = p
        return p

    def _play_chime(self):
        if self.app.sim:
            log.info("*chime*")
            return
        try:
            subprocess.run(["paplay", self._chime_path()], capture_output=True, timeout=10)
        except Exception as e:
            log.info("chime failed: %s", e)

    # --- birthday greeting (called by App when the camera recognises somebody)
    def greet(self, name):
        """-> True when a celebration was started. Only once per calendar day per person."""
        today = date.today()
        todays = self.store.for_person_today(name, today)
        done = False
        for ev in todays:
            key = "%s|%s|%s" % (today.isoformat(), (ev.get("person") or ev.get("name")).lower(), ev["kind"])
            if key in self.st["greeted"]:
                continue
            self.st["greeted"].append(key)
            self.st["greeted"] = [k for k in self.st["greeted"] if k.startswith(today.isoformat())][-50:]
            self._save()
            a = self.app
            a.mark_activity()
            a.say(self.store.greeting_text(ev), "joy" if ev["kind"] == "birthday" else "love", 9)
            a.toast("Happy %s, %s!" % (KIND_LABEL[ev["kind"]], ev.get("person") or ev.get("name")), 6)
            done = True
        return done


# =============================================================================== screen
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class CalendarScreen(Screen):
    name, title, accent = "calendar", "Calendar", (255, 150, 100)
    mini_pos = "br"

    def enter(self, **kw):
        t = date.today()
        self.year, self.month, self.sel = t.year, t.month, t
        self.press = None
        self.msg = ""

    def resume(self):
        pass

    # ---------------------------------------------------------------- geometry
    def _grid(self):
        u = self.u
        return pygame.Rect(int(24 * u), int(150 * u), int(self.w * 0.60), int(self.h - 170 * u))

    def _cells(self):
        g = self._grid()
        cw, ch = g.width / 7.0, g.height / 6.0
        weeks = pycal.Calendar(firstweekday=0).monthdayscalendar(self.year, self.month)
        out = []
        for r, wk in enumerate(weeks):
            for c, day in enumerate(wk):
                if day:
                    out.append((day, pygame.Rect(int(g.left + c * cw), int(g.top + r * ch), int(cw - 4), int(ch - 4))))
        return out

    def _nav(self):
        u = self.u
        return {"prev": pygame.Rect(int(24 * u), int(88 * u), int(56 * u), int(48 * u)),
                "next": pygame.Rect(int(self.w * 0.60 - 32 * u), int(88 * u), int(56 * u), int(48 * u)),
                "today": pygame.Rect(int(self.w * 0.60 + 50 * u), int(88 * u), int(110 * u), int(48 * u))}

    def _panel(self):
        u = self.u
        x = self.w * 0.60 + 40 * u
        return pygame.Rect(int(x), int(150 * u), int(self.w - x - 20 * u), int(self.h - 170 * u))

    def _add_rect(self):
        p = self._panel()
        u = self.u
        return pygame.Rect(p.left, int(p.top + 40 * u), p.width, int(54 * u))

    def _ev_rows(self):
        u, p = self.u, self._panel()
        evs = self.app.cal.on(self.sel)
        rows = []
        for i, e in enumerate(evs[:5]):
            r = pygame.Rect(p.left, int(p.top + 106 * u + i * 62 * u), p.width, int(54 * u))
            rows.append((e, r, pygame.Rect(r.right - int(52 * u), r.top, int(52 * u), r.height)))
        return rows

    # ---------------------------------------------------------------- draw
    @guarded("draw")
    def draw(self, surf):
        u = self.u
        cal = self.app.cal
        surf.fill(BG)
        self.topbar(surf, "Calendar")
        for n, r in self._nav().items():
            button(surf, r, self.accent)
            if n == "prev":
                icon_arrow(surf, r.centerx, r.centery, 16 * u, TEXT, True)
            elif n == "next":
                icon_arrow(surf, r.centerx, r.centery, 16 * u, TEXT, False)
            else:
                self.text(surf, "Today", r.centerx, r.centery - 11 * u, 20, TEXT, center=True)
        title = "%s %d" % (pycal.month_name[self.month], self.year)
        self.text(surf, title, (self._nav()["prev"].right + self._nav()["next"].left) / 2, 94 * u, 30, TEXT, center=True)
        g = self._grid()
        cw = g.width / 7.0
        for c, wd in enumerate(WEEKDAYS):
            self.text(surf, wd, g.left + c * cw + cw / 2 - 2, 124 * u, 17, MUTED, center=True)
        marks = cal.month_marks(self.year, self.month)
        today = date.today()
        for day, r in self._cells():
            d = date(self.year, self.month, day)
            col = self.accent if d == self.sel else (MUTED if d.weekday() >= 5 else TEXT)
            pygame.draw.rect(surf, mix(CARD, self.accent, 0.35) if d == self.sel else CARD, r, border_radius=int(10 * u))
            pygame.draw.rect(surf, GREEN if d == today else mix(CARD, MUTED, 0.3), r, width=3 if d == today else 1, border_radius=int(10 * u))
            self.text(surf, str(day), r.left + 8 * u, r.top + 4 * u, 20, col)
            for k, kind in enumerate(marks.get(day, [])[:3]):
                pygame.draw.circle(surf, KIND_COL[kind], (int(r.left + 14 * u + k * 16 * u), int(r.bottom - 12 * u)), int(5 * u))
        p = self._panel()
        pygame.draw.rect(surf, mix(BG, self.accent, 0.08), p, border_radius=int(16 * u))
        self.text(surf, self.sel.strftime("%a, %d %b %Y").replace(" 0", " "), p.left + 14 * u, p.top + 8 * u, 21, TEXT, maxw=p.width - 24 * u)
        ar = self._add_rect()
        button(surf, ar, GREEN)
        icon(surf, "plus", ar.left + 34 * u, ar.centery, 14 * u, GREEN)
        self.text(surf, "Add event", ar.left + 64 * u, ar.centery - 11 * u, 20, TEXT)
        rows = self._ev_rows()
        if not rows:
            self.text(surf, "Nothing planned", p.centerx, p.top + 130 * u, 19, MUTED, False, center=True)
        for e, r, tr in rows:
            col = KIND_COL[e["kind"]]
            pygame.draw.rect(surf, mix(CARD, col, 0.18), r, border_radius=int(12 * u))
            pygame.draw.rect(surf, col, r, width=2, border_radius=int(12 * u))
            self.text(surf, cal.title_of(e), r.left + 12 * u, r.top + 6 * u, 18, TEXT, maxw=r.width - 70 * u)
            sub = KIND_LABEL[e["kind"]] + (" - linked to profile" if e.get("person") else "")
            self.text(surf, sub, r.left + 12 * u, r.top + 30 * u, 14, MUTED, False, maxw=r.width - 70 * u)
            from .screens import icon_trash
            icon_trash(surf, tr.centerx, tr.centery, 16 * u, RED)

    # ---------------------------------------------------------------- input
    def on_down(self, pos):
        self.press = pos

    @guarded("on_up")
    def on_up(self, pos):
        if self.press is None:
            return
        self.press = None
        for n, r in self._nav().items():
            if inside(pos, r):
                if n == "today":
                    t = date.today()
                    self.year, self.month, self.sel = t.year, t.month, t
                else:
                    m = self.month + (1 if n == "next" else -1)
                    self.year += (m > 12) - (m < 1)
                    self.month = (m - 1) % 12 + 1
                    self.sel = date(self.year, self.month, min(self.sel.day, pycal.monthrange(self.year, self.month)[1]))
                return
        for day, r in self._cells():
            if inside(pos, r):
                self.sel = date(self.year, self.month, day)
                return
        if inside(pos, self._add_rect()):
            self._add_flow()
            return
        for e, r, tr in self._ev_rows():
            if inside(pos, tr):
                self.app.confirm("Delete %s?" % self.app.cal.title_of(e), lambda eid=e["id"]: self._delete(eid), "Delete", danger=True)
                return

    def _delete(self, eid):
        self.app.cal.delete(eid)
        self.app.toast("Event deleted")

    # ---------------------------------------------------------------- add-event flow
    def _add_flow(self):
        a = self.app
        a.choose("What kind of event on %s?" % self.sel.strftime("%d %b"), [
            ("Birthday", "Linked to a person Luna knows", lambda: self._pick_person("birthday"), (255, 120, 170)),
            ("Anniversary", "Wedding, friendship ...", lambda: self._pick_person("anniversary"), AMBER),
            ("Custom event", "Exam, trip, meeting ...", self._custom, BLUE)], self.accent)

    def _pick_person(self, kind):
        a = self.app
        opts = [(n, "Luna knows this face", (lambda nm=n: self._save(kind, nm, nm)), GREEN) for n in a.people.names()[:12]]
        opts.append(("Someone else...", "Type a name", lambda: a.ask_text("Name for the %s" % KIND_LABEL[kind].lower(), "", lambda t: self._save(kind, t, None) if t else None), BLUE))
        a.choose("Whose %s?" % KIND_LABEL[kind].lower(), opts, KIND_COL[kind])

    def _custom(self):
        a = self.app

        def got(t):
            if not t:
                return
            a.choose("Repeat?", [("Every year", "Same day each year", lambda: self._save("custom", "", None, t, True), GREEN),
                                 ("Only this day", "One time", lambda: self._save("custom", "", None, t, False), BLUE)], self.accent)
        a.ask_text("Event title", "", got)

    def _save(self, kind, name, person, title="", yearly=None):
        a = self.app
        try:
            ev = a.cal.add(kind, self.sel.month, self.sel.day, name=name, title=title, year=self.sel.year if yearly is False else None,
                           yearly=yearly, person=person)
            a.toast("Saved: %s" % a.cal.title_of(ev), 3)
        except Exception as e:
            log.exception("calendar save")
            a.toast("Could not save the event", 3)

    def context(self):
        evs = self.app.cal.on(self.sel)
        return "The calendar showing %s %d. Selected day has %d event(s)." % (pycal.month_name[self.month], self.year, len(evs))

    def comment(self):
        return "Tap a day to see its events, or press Add event. I will remind you the day before."
