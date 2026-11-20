"""Apps: gallery, music, movies, camera, drawing, manual room analysis, video playback."""
import hashlib
import math
import os
import random
import time

import pygame

from .analysis import AnalysisScreen
from .face import font
from .media import is_video
from .screens import (AMBER, BG, BLUE, CARD, GREEN, MUTED, PURPLE, RED, TEXT, TRACK, WHITE, GalleryScreen, ViewerScreen, button, fit,
                      icon_arrow, inside, load_image)
from .ui import ListView, Screen, ic_loop, ic_next, ic_seek, icon
from .util import clamp, mix


# ----------------------------------------------------------------------------- gallery
class GalleryApp(Screen):
    """Pictures + videos. Modes: normal, hidden (PIN), security (photos of visitors), pick (choose photos for a person)."""
    name, accent = "gallery", BLUE

    def __init__(self, app):
        super().__init__(app)
        self.g = GalleryScreen(app.size)
        self.g.video_thumb = lambda p: app.vlib.thumb(p)
        self.v = ViewerScreen(app.size)
        self.mode = "normal"
        self.viewing = False
        self.cb = None
        self.pending_hide = None
        self.vdown = None

    def enter(self, mode="normal", select=0, cb=None, files=None, index=None, **kw):
        self.mode, self.cb, self.viewing = mode, cb, False
        if mode == "hidden" and not self.app.vault.is_unlocked():     # the vault is only reachable through VaultManager
            mode = self.mode = "normal"
            self.app.toast("The hidden gallery is locked")
        self.list_files = files
        self.title = {"normal": "Gallery", "hidden": "Hidden Gallery", "security": "Security photos", "pick": "Choose photos", "list": "Pictures"}[mode]
        self.reload()
        if mode == "list" and index is not None:
            self._open(index)

    def reload(self, select=None):
        a = self.app
        if self.mode == "security":
            self.g.open(a.sec.photos(), False, "Security photos", RED, 0, False, True)
        elif self.mode == "list":
            self.g.open(list(self.list_files or []), False, "Pictures", BLUE, 0, False)
        elif self.mode == "pick":
            files = [p for p in a.store.list(False) if not is_video(p)]
            self.g.open(files, False, "Choose photos", GREEN, getattr(self, "limit", 10), False)
        elif self.mode == "hidden":
            if a.vault.is_unlocked():
                self.g.open(a.vault.list_files(), True)
            else:                                              # session ended -> normal gallery, never the OS
                self.mode, self.title = "normal", "Gallery"
                self.g.open(a.store.list(False), False)
        else:
            self.g.open(a.store.list(False), False)

    def leave(self):
        if self.mode == "hidden":
            self.app.vault.lock()

    def tick(self, dt):
        if self.mode == "hidden":
            if not self.app.vault.is_unlocked():                 # session expired -> back to the normal gallery
                self.mode, self.title, self.viewing = "normal", "Gallery", False
                self.reload()
                self.app.toast("Hidden gallery locked")

    def set_pick(self, limit, cb):
        self.mode, self.limit, self.cb, self.viewing = "pick", limit, cb, False
        self.title = "Choose photos"
        self.reload()

    @property
    def hidden(self):
        return self.mode == "hidden"

    def draw(self, surf):
        if self.viewing:
            self.v.draw(surf)
        else:
            self.g.draw(surf)
        if not self.viewing:
            r = self.back_rect()
            button(surf, r, TEXT)
            icon_arrow(surf, r.centerx, r.centery, 18 * self.u, TEXT, True)

    # --- input
    def down(self, pos):
        self.app.vault.touch()
        if self.viewing:
            self.vdown = pos
            return
        if inside(pos, self.back_rect()):
            self._back_down = True
            return
        self.g.pointer_down(pos)

    def move(self, pos):
        if not self.viewing and not self._back_down:
            self.g.pointer_move(pos)

    def up(self, pos):
        if self.viewing:
            act = self.v.swipe(self.vdown, pos) if self.vdown else None
            act = act or self.v.click(pos)
            self.vdown = None
            self._viewer_action(act)
            return
        if self._back_down:
            self._back_down = False
            if inside(pos, self.back_rect()):
                self.on_back()
            return
        ev = self.g.pointer_up(pos)
        if not ev:
            return
        kind, val = ev
        if kind == "lock":
            if self.hidden:
                self.app.vault.lock()
                self.mode = "normal"
                self.title = "Gallery"
                self.reload()
            else:
                self.app.request_hidden(replace=False)
        elif kind == "open":
            self._open(val)
        elif kind == "done":
            cb, self.cb = self.cb, None
            self.app.back()
            if cb:
                cb(val)

    def on_back(self):
        if self.viewing:
            self.viewing = False
            self.reload()
        else:
            self.app.back()

    def _open(self, idx):
        files = self.g.files
        if not files:
            return
        idx %= len(files)
        path = files[idx]
        if is_video(path):
            self.app.play_video(path)
            return
        self.v.open(path, controls=True, hidden=self.hidden, index=idx, count=len(files), allow_hide=self.mode in ("normal", "hidden"), allow_copy=self.mode == "list")
        self.viewing = True

    def _viewer_action(self, act):
        if not act:
            return
        a, idx = self.app, self.v.index
        if act == "close":
            self.viewing = False
            self.reload()
        elif act in ("prev", "next"):
            self._open(idx + (1 if act == "next" else -1))
        elif act == "copy":
            src = self.v.path
            a.run_bg(lambda: __import__("buddy.files", fromlist=["x"]).copy_into(src, a.cfg.GALLERY_DIR), lambda r: a.toast("Copied to Gallery" if r else "Copy failed", 3))
        elif act == "delete" and self.mode == "list":
            a.toast("Files from a USB drive are read-only here")
        elif act == "delete":
            if self.mode == "security":
                try:
                    os.remove(self.v.path)
                except OSError:
                    pass
            else:
                a.store.delete(self.v.path)
            self.reload()
            self.viewing = False
            if self.g.files:
                self._open(min(idx, len(self.g.files) - 1))
        elif act == "hide":
            path, hidden = self.v.path, self.hidden
            if not hidden and not a.pins.is_set():
                self.pending_hide = path
                a.open("pin", mode="setup", pins=a.pins, label="Hidden gallery PIN", on_done=self._pin_set)
                return
            a.store.move(path, not hidden)
            self.reload()
            self.viewing = False
            if self.g.files:
                self._open(min(idx, len(self.g.files) - 1))

    def _pin_set(self, res):
        if res == "pin_set" and self.pending_hide:
            self.app.store.move(self.pending_hide, True)
            self.app.toast("Picture hidden")
        self.pending_hide = None
        self.viewing = False
        self.reload()

    def context(self):
        n = len(self.g.files)
        return "The %s with %d items." % (self.title.lower(), n)

    def comment(self):
        n = len(self.g.files)
        return "You have %d item%s here. Tap one to open it, or say, Luna, take a selfie." % (n, "" if n == 1 else "s") if n else "It is empty. Shall we take a picture?"


# ----------------------------------------------------------------------------- movies
class MoviesScreen(Screen):
    name, title, accent = "movies", "Movies", (255, 160, 70)

    def __init__(self, app):
        super().__init__(app)
        self.g = GalleryScreen(app.size)
        self.g.video_thumb = lambda p: app.vlib.thumb(p)
        self.msg = ""

    def enter(self, **kw):
        self.reload()

    def reload(self):
        self.g.open(self.app.vlib.movies(), False, "Movies", self.accent, 0, False, True)
        self.g.caption_fn = lambda p: self.app.vlib.title(p)

    def _usb(self):
        return self.g.action_rect()

    def draw(self, surf):
        self.g.draw(surf)
        r = self.back_rect()
        button(surf, r, TEXT)
        icon_arrow(surf, r.centerx, r.centery, 18 * self.u, TEXT, True)
        b = self._usb()
        b = pygame.Rect(b.left - int(90 * self.u), b.top, int(b.width + 90 * self.u), b.height)
        button(surf, b, self.accent)
        self.text(surf, "Import USB", b.centerx, b.centery - 11 * self.u, 18, TEXT, center=True)
        if not self.g.files:
            self.text(surf, "Copy .mp4 / .mkv movies into  data/movies  or use a USB drive:  Luna/Movies/", self.w / 2, self.h * 0.42 + 90 * self.u, 16, MUTED, False, center=True)

    def on_down(self, pos):
        self.g.pointer_down(pos)

    def on_move(self, pos):
        self.g.pointer_move(pos)

    def on_up(self, pos):
        b = self._usb()
        b = pygame.Rect(b.left - int(90 * self.u), b.top, int(b.width + 90 * self.u), b.height)
        if inside(pos, b) and self.g.down is not None and self.g.moved < 14:
            self.g.down = None
            self.app.import_usb()
            self.reload()
            return
        ev = self.g.pointer_up(pos)
        if ev and ev[0] == "open":
            self.app.play_video(self.g.files[ev[1]])

    def context(self):
        return "The Movies screen with %d videos." % len(self.g.files)

    def comment(self):
        n = len(self.g.files)
        return "You have %d movie%s. Tap one to play it. Tap the screen to pause, double tap to leave." % (n, "" if n == 1 else "s") if n else \
            "There are no movies yet. Copy some into the movies folder or import them from a USB drive."


class VideoPlayScreen(Screen):
    name, mini, has_back = "video", False, False

    def enter(self, path="", **kw):
        self.path = path
        self.started = time.time()

    def draw(self, surf):
        surf.fill((0, 0, 0))
        self.text(surf, "Playing: %s" % self.app.vlib.title(self.path), self.w / 2, self.h * 0.42, 30, TEXT, center=True)
        self.text(surf, "Touch = pause / play     double-tap = stop     say: Luna pause, resume, forward, rewind, stop", self.w / 2, self.h * 0.52, 17, MUTED, False, center=True)

    def tick(self, dt):
        if time.time() - self.started > 1.5 and not self.app.video.running():
            self.app.end_video()

    def context(self):
        return "A video is playing: %s." % self.app.vlib.title(self.path)


# ----------------------------------------------------------------------------- music
ALBUM_COL = [(255, 200, 90), (255, 110, 150), (255, 150, 60), (110, 150, 255), (110, 220, 200), (140, 220, 110), (210, 160, 120)]


class MusicScreen(Screen):
    name, title, accent = "music", "Music", (255, 120, 170)
    mini_pos = "br"

    def __init__(self, app):
        super().__init__(app)
        self.view, self.album = "albums", None
        self.lv = ListView(self.u)
        self.down_pos = None
        self.albums_scroll = 0.0
        self.msg = ""

    def enter(self, album=None, **kw):
        self.view, self.album = ("tracks", album) if album else ("albums", None)
        self.title = album or "Music"
        self._rows()

    def on_back(self):
        if self.view == "tracks":
            self.view, self.title, self.album = "albums", "Music", None
        else:
            self.app.back()

    def _rows(self):
        if self.view == "tracks":
            cur = self.app.player.status()
            rows = []
            for i, t in enumerate(self.app.mlib.tracks(self.album)):
                playing = cur["active"] and cur["title"] == t.title
                rows.append(dict(label=t.title, sub=t.album, icon="music", tag=i, col=GREEN if playing else self.accent, hl=playing,
                                 right="playing" if playing else "", rcol=GREEN))
            self.lv.set_rows(rows, keep=True)

    # layout
    def _bar(self):
        u = self.u
        return pygame.Rect(0, int(self.h - 138 * u), self.w, int(138 * u))

    def _tiles(self):
        u, w = self.u, self.w
        albums = self.app.mlib.albums()
        cols, gap = 4, 16 * u
        tw = (w - 2 * 30 * u - (cols - 1) * gap) / cols
        th = 118 * u
        out = []
        for i in range(len(albums) + 1):
            r, c = divmod(i, cols)
            out.append((albums[i] if i < len(albums) else None,
                        pygame.Rect(int(30 * u + c * (tw + gap)), int(100 * u + r * (th + gap) - self.albums_scroll), int(tw), int(th))))
        return out

    def _btns(self):
        u = self.u
        bar = self._bar()
        names = ["loop", "prev", "back", "play", "fwd", "next", "shuffle"]
        sizes = [64, 64, 64, 84, 64, 64, 64]
        total = sum(sizes) * u + (len(names) - 1) * 14 * u
        x = 40 * u
        out = {}
        for n, s in zip(names, sizes):
            out[n] = pygame.Rect(int(x), int(bar.top + 52 * u + (84 - s) * u / 2), int(s * u), int(s * u))
            x += s * u + 14 * u
        return out

    def _prog(self):
        u = self.u
        bar = self._bar()
        return pygame.Rect(int(40 * u), int(bar.top + 38 * u), int(self.w - 80 * u), int(12 * u))

    def draw(self, surf):
        u, w, h = self.u, self.w, self.h
        surf.fill(BG)
        self.topbar(surf, self.album or "Music")
        a = self.app
        if self.view == "albums":
            for al, r in self._tiles():
                if r.bottom < 80 * u or r.top > self._bar().top:
                    continue
                if al is None:
                    pygame.draw.rect(surf, CARD, r, border_radius=int(16 * u))
                    pygame.draw.rect(surf, MUTED, r, width=2, border_radius=int(16 * u))
                    icon(surf, "plus", r.centerx, r.centery - 12 * u, 22 * u, MUTED)
                    self.text(surf, "New album", r.centerx, r.bottom - 36 * u, 18, MUTED, center=True)
                    continue
                col = ALBUM_COL[int(hashlib.md5(al.encode()).hexdigest(), 16) % len(ALBUM_COL)]
                pygame.draw.rect(surf, mix(CARD, col, 0.16), r, border_radius=int(16 * u))
                pygame.draw.rect(surf, mix(CARD, col, 0.6), r, width=2, border_radius=int(16 * u))
                icon(surf, "music", r.left + 44 * u, r.centery - 8 * u, 22 * u, col)
                self.text(surf, al, r.left + 84 * u, r.centery - 28 * u, 21, TEXT, maxw=r.width - 96 * u)
                self.text(surf, "%d song%s" % (a.mlib.count(al), "" if a.mlib.count(al) == 1 else "s"), r.left + 84 * u, r.centery + 2 * u, 16, MUTED, False)
            ub = pygame.Rect(int(w - 190 * u), int(14 * u), int(170 * u), int(50 * u))
            button(surf, ub, self.accent)
            self.text(surf, "Import USB", ub.centerx, ub.centery - 11 * u, 18, TEXT, center=True)
            self.text(surf, self.msg or "Copy songs into  data/music/<album>/  or import from a USB drive (Luna/Music/<album>/)", w / 2, self._bar().top - 26 * u, 14, MUTED, False, center=True)
        else:
            self._rows()
            self.lv.draw(surf, pygame.Rect(int(40 * u), int(94 * u), int(w - 80 * u), int(self._bar().top - 104 * u)), self.accent)
            if not self.lv.rows:
                self.text(surf, "No songs in this album yet", w / 2, 240 * u, 26, MUTED, center=True)
                self.text(surf, "Copy audio files into data/music/%s/ or import from USB" % self.album, w / 2, 280 * u, 16, MUTED, False, center=True)
        self._draw_bar(surf)

    def _draw_bar(self, surf):
        u, w = self.u, self.w
        bar = self._bar()
        st = self.app.player.status()
        pygame.draw.rect(surf, mix(BG, self.accent, 0.14), bar)
        pygame.draw.line(surf, self.accent, (0, bar.top), (w, bar.top), 2)
        title = st["title"] if st["active"] else "Nothing playing"
        self.text(surf, title + ("   -   %s" % st["album"] if st["active"] and st["album"] else ""), 40 * u, bar.top + 6 * u, 20, TEXT, maxw=w - 80 * u)
        pr = self._prog()
        pygame.draw.rect(surf, TRACK, pr, border_radius=6)
        frac = clamp(st["pos"] / st["dur"], 0, 1) if st["dur"] else 0
        fw = int(pr.width * frac)
        if fw > 2:
            pygame.draw.rect(surf, self.accent, pygame.Rect(pr.left, pr.top, fw, pr.height), border_radius=min(6, fw // 2))
        pygame.draw.circle(surf, TEXT, (pr.left + fw, pr.centery), int(9 * u))
        mm = lambda s: "%d:%02d" % (int(s) // 60, int(s) % 60)
        self.text(surf, mm(st["pos"]), 40 * u, pr.bottom + 2 * u, 14, MUTED, False)
        d = font(14 * u, False).render(mm(st["dur"]), True, MUTED)
        surf.blit(d, (w - 40 * u - d.get_width(), pr.bottom + 2 * u))
        for n, r in self._btns().items():
            on = (n == "loop" and st["loop"] != "off") or (n == "shuffle" and self.app.shuffle)
            col = GREEN if on else TEXT
            button(surf, r, col if on else MUTED, mix(CARD, self.accent, 0.5) if n == "play" else None)
            cx, cy, s = r.centerx, r.centery, r.width * 0.28
            if n == "play":
                icon(surf, "pause" if st["playing"] else "play", cx, cy, s * 1.2, TEXT)
            elif n == "loop":
                ic_loop(surf, cx, cy, s, col, one=st["loop"] == "one")
            elif n == "prev":
                ic_next(surf, cx, cy, s, TEXT, flip=True)
            elif n == "next":
                ic_next(surf, cx, cy, s, TEXT)
            elif n in ("back", "fwd"):
                ic_seek(surf, cx, cy - 4 * u, s * 0.9, TEXT, back=(n == "back"))
                self.text(surf, "10", cx, cy + 6 * u, 14, TEXT, center=True)
            elif n == "shuffle":
                icon(surf, "shuffle", cx, cy, s, col)

    # input
    def on_down(self, pos):
        self.down_pos = pos
        self._last = pos
        self._moved = 0
        if self.view == "tracks" and pos[1] < self._bar().top:
            self.lv.down(pos)

    def on_move(self, pos):
        if self.view == "tracks":
            self.lv.move(pos)
        elif self.down_pos:
            dy = pos[1] - self._last[1]
            self._moved += abs(dy)
            self._last = pos
            if self._moved > 14 * self.u:
                rows = (len(self.app.mlib.albums()) + 1 + 3) // 4
                mx = max(0.0, rows * (118 + 16) * self.u - (self._bar().top - 100 * self.u))
                self.albums_scroll = clamp(self.albums_scroll - dy, 0, mx)

    def on_up(self, pos):
        a = self.app
        # player controls
        for n, r in self._btns().items():
            if inside(pos, r):
                self._control(n)
                self.lv.down_pos = None
                return
        if inside(pos, self._prog().inflate(0, int(30 * self.u))):
            a.player.seek_to(clamp((pos[0] - self._prog().left) / float(self._prog().width), 0, 1))
            return
        if self.view == "tracks":
            tag = self.lv.up(pos)
            if tag is not None:
                a.play_album(self.album, tag)
            return
        self.down_pos = None
        if getattr(self, "_moved", 0) > 14 * self.u:
            return
        ub = pygame.Rect(int(self.w - 190 * self.u), int(14 * self.u), int(170 * self.u), int(50 * self.u))
        if inside(pos, ub):
            self.msg = a.import_usb()
            return
        for al, r in self._tiles():
            if inside(pos, r) and pos[1] < self._bar().top:
                if al is None:
                    a.ask_text("New album name", "", self._new_album, hint="for example: Road trip, Study, Bhajans")
                else:
                    self.view, self.album, self.title = "tracks", al, al
                    self._rows()
                return

    def _new_album(self, name):
        if name and name.strip():
            n = self.app.mlib.create_album(name)
            self.app.toast("Album '%s' created" % n if n else "Invalid name")

    def _control(self, n):
        a = self.app
        p = a.player
        if n == "play":
            p.toggle() if p.status()["active"] else (a.play_album(self.album, 0) if self.album else a.toast("Pick a song first"))
        elif n == "next":
            p.next()
        elif n == "prev":
            p.prev()
        elif n == "fwd":
            p.seek(a.cfg.SEEK_SECONDS)
        elif n == "back":
            p.seek(-a.cfg.SEEK_SECONDS)
        elif n == "loop":
            a.cycle_loop()
        elif n == "shuffle":
            a.shuffle = not a.shuffle
            a.toast("Shuffle %s" % ("on" if a.shuffle else "off"))

    def context(self):
        st = self.app.player.status()
        now = "Playing %s." % st["title"] if st["playing"] else "Music is paused." if st["active"] else "Nothing is playing."
        return "The Music app showing %s. %s" % ("the %s album" % self.album if self.album else "all albums", now)

    def comment(self):
        st = self.app.player.status()
        if st["playing"]:
            return "Nice choice. %s sounds great. Say, Luna, next song, if you want something different." % st["title"]
        return "Try saying, Luna, play a chill song, or tap an album."


# ----------------------------------------------------------------------------- camera app
class CameraAppScreen(Screen):
    name, title, accent = "camera", "Camera", (120, 210, 255)
    mini = True

    def enter(self, mode="photo", **kw):
        self.mode = mode
        self.flash_until = 0.0
        self.last = None
        self.thumb = None

    def _shutter(self):
        u = self.u
        return pygame.Rect(int(self.w / 2 - 44 * u), int(self.h - 112 * u), int(88 * u), int(88 * u))

    def _mode_btn(self):
        u = self.u
        return pygame.Rect(int(self.w / 2 - 110 * u), int(12 * u), int(220 * u), int(52 * u))

    def draw(self, surf):
        u, w, h = self.u, self.w, self.h
        cam = self.app.camera
        surf.fill((0, 0, 0))
        pv = cam.preview_surface(mirror=False)
        if pv is not None:
            iw, ih = pv.get_size()
            k = min(w / iw, h / ih)
            surf.blit(pygame.transform.smoothscale(pv, (int(iw * k), int(ih * k))), ((w - int(iw * k)) // 2, (h - int(ih * k)) // 2))
        else:
            self.text(surf, "No camera preview", w / 2, h / 2, 30, MUTED, center=True)
        pygame.draw.rect(surf, (0, 0, 0), pygame.Rect(0, 0, w, int(76 * u)))
        r = self.back_rect()
        button(surf, r, TEXT)
        icon_arrow(surf, r.centerx, r.centery, 18 * u, TEXT, True)
        m = self._mode_btn()
        button(surf, m, self.accent)
        half = m.width // 2
        for i, (lab, key) in enumerate((("Photo", "photo"), ("Video", "video"))):
            if self.mode == key:
                pygame.draw.rect(surf, mix(CARD, self.accent, 0.5), pygame.Rect(m.left + i * half, m.top, half, m.height), border_radius=int(m.height * 0.28))
            self.text(surf, lab, m.left + i * half + half / 2, m.centery - 11 * u, 20, TEXT, center=True)
        pygame.draw.rect(surf, (0, 0, 0), pygame.Rect(0, int(h - 130 * u), w, int(130 * u)))
        s = self._shutter()
        rec = cam.recording
        pygame.draw.circle(surf, WHITE, s.center, int(44 * u), 5)
        if self.mode == "video":
            if rec:
                pygame.draw.rect(surf, RED, pygame.Rect(s.centerx - int(20 * u), s.centery - int(20 * u), int(40 * u), int(40 * u)), border_radius=6)
            else:
                pygame.draw.circle(surf, RED, s.center, int(32 * u))
        else:
            pygame.draw.circle(surf, WHITE, s.center, int(34 * u))
        if rec:
            t = int(time.time() - cam.rec_start)
            self.text(surf, "REC %02d:%02d" % (t // 60, t % 60), w / 2, 84 * u, 24, RED, center=True)
        g = pygame.Rect(int(40 * u), int(h - 108 * u), int(150 * u), int(80 * u))
        button(surf, g, MUTED)
        icon(surf, "gallery", g.left + 40 * u, g.centery, 18 * u, TEXT)
        self.text(surf, "Gallery", g.left + 72 * u, g.centery - 11 * u, 18, TEXT)
        if time.time() < self.flash_until:
            surf.fill(WHITE)

    def on_up(self, pos):
        a = self.app
        if inside(pos, self._mode_btn()):
            if not a.camera.recording:
                self.mode = "video" if pos[0] > self._mode_btn().centerx else "photo"
            return
        if inside(pos, self._shutter()):
            if self.mode == "photo":
                self.take_photo()
            else:
                a.toggle_recording()
            return
        u = self.u
        if inside(pos, pygame.Rect(int(40 * u), int(self.h - 108 * u), int(150 * u), int(80 * u))):
            a.open("gallery", mode="normal")

    def take_photo(self):
        a = self.app
        path = a.store.new_photo_path()
        if a.camera.capture_jpeg(path):
            a.last_photo = path
            a.speaker.shutter()
            self.flash_until = time.time() + 0.15
            a.toast("Photo saved to Gallery")
        else:
            a.toast("Camera not ready")

    def on_back(self):
        if self.app.camera.recording:
            self.app.toggle_recording()
        self.app.back()

    def leave(self):
        if self.app.camera.recording:
            self.app.toggle_recording()

    def context(self):
        return "The Camera app in %s mode%s." % (self.mode, ", currently recording" if self.app.camera.recording else "")

    def comment(self):
        return "Ready when you are. Tap the big button to take a %s." % ("picture" if self.mode == "photo" else "video")


# ----------------------------------------------------------------------------- drawing
COLORS = [(20, 20, 20), (255, 255, 255), (230, 50, 50), (255, 140, 0), (250, 210, 30), (60, 190, 90), (30, 170, 170), (50, 110, 240),
          (120, 70, 220), (230, 80, 180), (140, 90, 50), (130, 130, 130)]
PEN_SIZES = [3, 7, 14, 26]
ERASER_SIZES = [20, 50]


class DrawingGallery(Screen):
    name, title, accent = "drawing", "Drawing", (190, 130, 255)

    def enter(self, **kw):
        self.scroll, self.down_pos, self.moved, self.cache = 0.0, None, 0.0, {}
        self.files = self.app.drawings()
        self.press_t = 0.0

    def _cell(self, i):
        u, w = self.u, self.w
        cols, gap = 4, 16 * u
        tw = (w - 60 * u - (cols - 1) * gap) / cols
        th = tw * 0.66
        r, c = divmod(i, cols)
        return pygame.Rect(int(30 * u + c * (tw + gap)), int(98 * u + r * (th + gap) - self.scroll), int(tw), int(th))

    def draw(self, surf):
        u = self.u
        surf.fill(BG)
        for i in range(len(self.files) + 1):
            r = self._cell(i)
            if r.bottom < 80 * u or r.top > self.h:
                continue
            if i == 0:
                pygame.draw.rect(surf, CARD, r, border_radius=int(14 * u))
                pygame.draw.rect(surf, self.accent, r, width=3, border_radius=int(14 * u))
                icon(surf, "plus", r.centerx, r.centery - 12 * u, 26 * u, self.accent)
                self.text(surf, "New drawing", r.centerx, r.bottom - 36 * u, 18, TEXT, center=True)
                continue
            p = self.files[i - 1]
            img = self.cache.get(p)
            if img is None:
                raw = load_image(p)
                if raw is not None:
                    iw, ih = raw.get_size()
                    img = pygame.transform.smoothscale(raw, (r.width, r.height))
                    self.cache[p] = img
            if img is not None:
                surf.blit(img, r.topleft)
            pygame.draw.rect(surf, mix(CARD, self.accent, 0.6), r, width=2, border_radius=6)
        pygame.draw.rect(surf, BG, pygame.Rect(0, 0, self.w, int(82 * u)))
        self.topbar(surf, "Drawing - your saved drawings", "tap + for a new board  -  hold to delete")

    def on_down(self, pos):
        self.down_pos, self._last, self.moved, self.press_t = pos, pos, 0.0, time.time()

    def on_move(self, pos):
        if self.down_pos:
            dy = pos[1] - self._last[1]
            self.moved += abs(dy)
            self._last = pos
            if self.moved > 14 * self.u:
                rows = (len(self.files) + 1 + 3) // 4
                mx = max(0.0, rows * (self._cell(0).height + 16 * self.u) - (self.h - 100 * self.u) + 20 * self.u)
                self.scroll = clamp(self.scroll - dy, 0, mx)

    def on_up(self, pos):
        if self.down_pos is None or self.moved > 14 * self.u:
            self.down_pos = None
            return
        held = time.time() - self.press_t
        self.down_pos = None
        for i in range(len(self.files) + 1):
            if inside(pos, self._cell(i)) and pos[1] > 80 * self.u:
                if i == 0:
                    self.app.open("canvas", path=None)
                elif held > 0.7:
                    p = self.files[i - 1]
                    self.app.confirm("Delete this drawing?", lambda p=p: (os.remove(p), self.enter()), "Delete", danger=True)
                else:
                    self.app.open("canvas", path=self.files[i - 1])
                return

    def context(self):
        return "The Drawing app showing %d saved drawings and a plus button for a new whiteboard." % len(self.files)

    def comment(self):
        return "Tap the plus to start a new whiteboard, or open an old drawing to continue it."


class DrawingCanvas(Screen):
    name, title, accent = "canvas", "Whiteboard", (190, 130, 255)
    mini_pos = "tr"

    def enter(self, path=None, **kw):
        u = self.u
        self.path = path
        self.top, self.bottom = int(70 * u), int(92 * u)
        self.cw, self.ch = self.w, self.h - self.top - self.bottom
        self.canvas = pygame.Surface((self.cw, self.ch))
        self.canvas.fill(WHITE)
        if path:
            img = load_image(path)
            if img is not None:
                self.canvas.blit(pygame.transform.smoothscale(img, (self.cw, self.ch)), (0, 0))
        self.undo, self.redo = [], []
        self.color, self.tool, self.size = 0, "pen", PEN_SIZES[1]
        self.dirty, self.strokes, self.used = False, 0, set()
        self.last = None

    # layout
    def _top_btns(self):
        u = self.u
        names = ["undo", "redo", "clear", "save"]
        return {n: pygame.Rect(int(self.w - (len(names) - i) * 74 * u - 8 * u), int(9 * u), int(64 * u), int(52 * u)) for i, n in enumerate(names)}

    def _swatches(self):
        u = self.u
        y = self.h - self.bottom + int(24 * u)
        return [(i, pygame.Rect(int(16 * u + i * 44 * u), int(y), int(38 * u), int(38 * u))) for i in range(len(COLORS))]

    def _tools(self):
        u = self.u
        x0 = 16 * u + len(COLORS) * 44 * u + 24 * u
        y = self.h - self.bottom + int(14 * u)
        out = []
        for i, s in enumerate(PEN_SIZES):
            out.append((("pen", s), pygame.Rect(int(x0 + i * 62 * u), int(y), int(56 * u), int(58 * u))))
        for i, s in enumerate(ERASER_SIZES):
            out.append((("eraser", s), pygame.Rect(int(x0 + (len(PEN_SIZES) + i) * 62 * u + 10 * u), int(y), int(56 * u), int(58 * u))))
        return out

    def draw(self, surf):
        u, w, h = self.u, self.w, self.h
        surf.fill((235, 235, 240))
        surf.blit(self.canvas, (0, self.top))
        pygame.draw.rect(surf, BG, pygame.Rect(0, 0, w, self.top))
        pygame.draw.rect(surf, BG, pygame.Rect(0, h - self.bottom, w, self.bottom))
        r = self.back_rect()
        r.height = int(50 * u)
        button(surf, r, TEXT)
        icon_arrow(surf, r.centerx, r.centery, 17 * u, TEXT, True)
        self.text(surf, "Whiteboard" + (" *" if self.dirty else ""), 92 * u, 20 * u, 26, TEXT)
        for n, rr in self._top_btns().items():
            button(surf, rr, GREEN if n == "save" else (RED if n == "clear" else MUTED))
            if n == "undo":
                from .ui import ic_undo
                ic_undo(surf, rr.centerx, rr.centery, 16 * u, TEXT)
            elif n == "redo":
                from .ui import ic_undo
                ic_undo(surf, rr.centerx, rr.centery, 16 * u, TEXT, redo=True)
            elif n == "clear":
                icon(surf, "trash", rr.centerx, rr.centery, 15 * u, RED)
            else:
                icon(surf, "save", rr.centerx, rr.centery, 15 * u, GREEN)
        for i, rr in self._swatches():
            pygame.draw.rect(surf, COLORS[i], rr, border_radius=int(8 * u))
            pygame.draw.rect(surf, TEXT if (i == self.color and self.tool == "pen") else (70, 80, 100), rr, width=4 if (i == self.color and self.tool == "pen") else 1, border_radius=int(8 * u))
        for (kind, s), rr in self._tools():
            sel = self.tool == kind and self.size == s
            button(surf, rr, GREEN if sel else MUTED, mix(CARD, GREEN, 0.3) if sel else None)
            if kind == "pen":
                pygame.draw.circle(surf, COLORS[self.color] if COLORS[self.color] != (20, 20, 20) or True else TEXT, rr.center, max(2, int(s * 0.5 * u * 0.9)))
            else:
                icon(surf, "eraser", rr.centerx, rr.centery - 4 * u, (10 if s < 30 else 15) * u, TEXT)
        self.text(surf, "Pen sizes", self._tools()[0][1].left, h - 14 * u - 2, 11, MUTED, False)

    # drawing
    def _in_canvas(self, pos):
        return self.top <= pos[1] < self.h - self.bottom

    def _stroke(self, a, b):
        col = (255, 255, 255) if self.tool == "eraser" else COLORS[self.color]
        w = self.size
        pa, pb = (a[0], a[1] - self.top), (b[0], b[1] - self.top)
        pygame.draw.line(self.canvas, col, pa, pb, w)
        pygame.draw.circle(self.canvas, col, (int(pb[0]), int(pb[1])), max(1, w // 2))

    def on_down(self, pos):
        if self._in_canvas(pos):
            self.undo.append(self.canvas.copy())
            self.undo = self.undo[-15:]
            self.redo = []
            self.last = pos
            self._stroke(pos, pos)
            self.dirty = True
            self.strokes += 1
            if self.tool == "pen":
                self.used.add(self.color)

    def on_move(self, pos):
        if self.last is not None and self._in_canvas(pos):
            self._stroke(self.last, pos)
            self.last = pos

    def on_up(self, pos):
        if self.last is not None:
            self.last = None
            return
        for n, r in self._top_btns().items():
            if inside(pos, r):
                self._top(n)
                return
        for i, r in self._swatches():
            if inside(pos, r):
                self.color = i
                if self.tool == "eraser":
                    self.tool, self.size = "pen", PEN_SIZES[1]
                return
        for (kind, s), r in self._tools():
            if inside(pos, r):
                self.tool, self.size = kind, s
                return

    def _top(self, n):
        a = self.app
        if n == "undo" and self.undo:
            self.redo.append(self.canvas.copy())
            self.canvas = self.undo.pop()
        elif n == "redo" and self.redo:
            self.undo.append(self.canvas.copy())
            self.canvas = self.redo.pop()
        elif n == "clear":
            a.confirm("Clear the whole board?", self._clear, "Clear", danger=True)
        elif n == "save":
            self.save()

    def _clear(self):
        self.undo.append(self.canvas.copy())
        self.canvas.fill(WHITE)
        self.dirty = True

    def save(self):
        a = self.app
        if not self.path:
            self.path = os.path.join(a.cfg.DRAWINGS_DIR, "DRAW_%s.png" % time.strftime("%Y%m%d_%H%M%S"))
        os.makedirs(a.cfg.DRAWINGS_DIR, exist_ok=True)
        pygame.image.save(self.canvas, self.path)
        self.dirty = False
        a.toast("Drawing saved")

    def on_back(self):
        if self.dirty:
            self.app.choose("Save this drawing?", [("Save and close", "Keep your work", lambda: (self.save(), self.app.back()), GREEN),
                                                   ("Discard", "Close without saving", lambda: self.app.back(), RED),
                                                   ("Keep drawing", "Go back to the board", None, BLUE)], self.accent)
        else:
            self.app.back()

    def priority_hit(self, pos):
        return pos[1] > self.h - self.bottom or pos[1] < self.top

    def context(self):
        names = {0: "black", 1: "white", 2: "red", 3: "orange", 4: "yellow", 5: "green", 6: "teal", 7: "blue", 8: "purple", 9: "pink", 10: "brown", 11: "grey"}
        cols = ", ".join(names[i] for i in sorted(self.used)) or "no colours yet"
        return "The drawing whiteboard with %d strokes, using %s. Current tool: %s." % (self.strokes, cols, self.tool)

    def comment(self):
        if self.strokes == 0:
            return "The board is empty. How about drawing a house, a tree, or maybe me? I would love a portrait."
        names = {0: "black", 2: "red", 3: "orange", 4: "yellow", 5: "green", 6: "teal", 7: "blue", 8: "purple", 9: "pink", 10: "brown"}
        cols = [names[i] for i in sorted(self.used) if i in names]
        if len(cols) >= 3:
            return "What a colourful drawing! I can see %s. Try adding some shading or a background." % ", ".join(cols[:3])
        return "That is a nice start. Try a different colour or a thicker pen to add some detail. Do not forget to save it."


# ----------------------------------------------------------------------------- analysis (manual, no timer)
class AnalysisApp(Screen):
    name, title, accent = "analysis", "Room analysis", GREEN

    def __init__(self, app):
        super().__init__(app)
        self.an = AnalysisScreen(app.size, 10)

    def enter(self, **kw):
        self.an.restart()

    def draw(self, surf):
        self.an.draw(surf, self.app.snap or self.app.sensors.snapshot(), manual=True)
        r = self.back_rect()
        button(surf, r, TEXT)
        icon_arrow(surf, r.centerx, r.centery, 18 * self.u, TEXT, True)

    def context(self):
        s = self.app.snap or {}
        return "The live room analysis: temperature %s C, humidity %s percent, air quality %s." % (s.get("temperature"), s.get("humidity"), s.get("aq_label"))

    def comment(self):
        return self.app.brain.summary()


from .util import harden as _harden          # noqa: E402  - error boundary for every click handler of the gallery
_harden(GalleryApp, ("enter", "reload", "down", "move", "up", "_open", "_viewer_action", "on_back", "draw"))
