"""Touch-screen UI: mini face, photo countdown, image viewer, gallery grid, PIN keypad."""
import json
import math
import os
import time

import pygame

from .face import Face, font
from .util import clamp, mix

BG = (8, 12, 22)
CARD = (17, 25, 42)
TRACK = (36, 48, 70)
TEXT = (230, 240, 255)
MUTED = (125, 145, 175)
BLUE = (90, 160, 255)
GREEN = (80, 225, 150)
AMBER = (255, 200, 70)
RED = (255, 90, 80)
PURPLE = (170, 120, 255)
WHITE = (255, 255, 255)


def inside(pos, rect):
    return rect.left <= pos[0] < rect.right and rect.top <= pos[1] < rect.bottom


def fit(surf_size, box_w, box_h):
    w, h = surf_size
    k = min(box_w / float(w), box_h / float(h))
    return max(1, int(w * k)), max(1, int(h * k))


def load_image(path):
    try:
        return pygame.image.load(path)
    except Exception:
        return None


def date_of(path):
    try:
        return time.strftime("%d %b %Y  %H:%M", time.localtime(os.path.getmtime(path)))
    except OSError:
        return ""


# ------------------------------------------------------------------- icons
def icon_gallery(surf, cx, cy, s, col):
    r = pygame.Rect(int(cx - s), int(cy - s * 0.8), int(2 * s), int(1.6 * s))
    pygame.draw.rect(surf, col, r, width=max(2, int(s * 0.12)), border_radius=int(s * 0.25))
    pygame.draw.circle(surf, col, (int(cx + s * 0.45), int(cy - s * 0.35)), int(s * 0.17))
    pygame.draw.polygon(surf, col, [(cx - s * 0.85, cy + s * 0.65), (cx - s * 0.3, cy - s * 0.1), (cx + s * 0.1, cy + s * 0.4),
                                    (cx + s * 0.4, cy + s * 0.1), (cx + s * 0.85, cy + s * 0.65)])


def icon_lock(surf, cx, cy, s, col, open_=False):
    pygame.draw.rect(surf, col, pygame.Rect(int(cx - s * 0.7), int(cy - s * 0.1), int(s * 1.4), int(s * 1.0)), border_radius=int(s * 0.2))
    r = s * 0.45
    sx = cx + (s * 0.5 if open_ else 0)
    sy = cy - s * 0.1 - (s * 0.28 if open_ else 0)
    pts = [(sx - r * math.cos(math.pi * i / 12), sy - r * 1.2 * math.sin(math.pi * i / 12)) for i in range(13)]
    pygame.draw.lines(surf, col, False, pts, max(2, int(s * 0.18)))
    pygame.draw.circle(surf, BG, (int(cx), int(cy + s * 0.3)), max(2, int(s * 0.14)))


def icon_trash(surf, cx, cy, s, col):
    pygame.draw.rect(surf, col, pygame.Rect(int(cx - s * 0.5), int(cy - s * 0.35), int(s), int(s * 1.0)), width=max(2, int(s * 0.14)), border_radius=int(s * 0.1))
    pygame.draw.line(surf, col, (cx - s * 0.7, cy - s * 0.4), (cx + s * 0.7, cy - s * 0.4), max(2, int(s * 0.16)))
    pygame.draw.rect(surf, col, pygame.Rect(int(cx - s * 0.2), int(cy - s * 0.65), int(s * 0.4), int(s * 0.25)))


def icon_x(surf, cx, cy, s, col):
    t = max(3, int(s * 0.2))
    pygame.draw.line(surf, col, (cx - s * 0.5, cy - s * 0.5), (cx + s * 0.5, cy + s * 0.5), t)
    pygame.draw.line(surf, col, (cx - s * 0.5, cy + s * 0.5), (cx + s * 0.5, cy - s * 0.5), t)


def icon_arrow(surf, cx, cy, s, col, left):
    d = -1 if left else 1
    pygame.draw.polygon(surf, col, [(cx + d * s * 0.5, cy), (cx - d * s * 0.4, cy - s * 0.6), (cx - d * s * 0.4, cy + s * 0.6)])


def button(surf, rect, col, fill=None):
    pygame.draw.rect(surf, fill or CARD, rect, border_radius=int(rect.height * 0.28))
    pygame.draw.rect(surf, col, rect, width=2, border_radius=int(rect.height * 0.28))


# --------------------------------------------------------------- mini face
class MiniFace:
    """Luna's face minimised into a corner. Long-press + drag to move, double-tap to go back to robot mode."""

    def __init__(self, size, state_file):
        self.sw, self.sh = size
        u = self.sh / 600.0
        self.w, self.h = int(216 * u), int(130 * u)
        self.face = Face((self.w, self.h))
        self.surf = pygame.Surface((self.w, self.h))
        self.state_file = state_file
        self.u = u
        self.user_set = False
        self.x, self.y = self.sw - self.w - int(16 * u), self.sh - self.h - int(16 * u)
        self._load()
        self.down_at = None
        self.down_pos = None
        self.grab = (0, 0)
        self.dragging = False
        self.last_tap = 0.0

    def _load(self):
        try:
            with open(self.state_file) as f:
                x, y = json.load(f)["mini"]
            self.x, self.y = int(clamp(x, 0, self.sw - self.w)), int(clamp(y, 0, self.sh - self.h))
            self.user_set = bool(json.load(open(self.state_file)).get("mini_user", False))
        except Exception:
            pass

    def snap(self, where):
        """Default corner for a screen (ignored once the user has dragged Luna somewhere herself)."""
        if self.user_set:
            return
        u, m = self.u, int(16 * self.u)
        top = int(86 * u)
        self.x = self.sw - self.w - m if "r" in where else m
        self.y = top if where.startswith("t") else self.sh - self.h - m

    def _save(self):
        try:
            data = {}
            if os.path.exists(self.state_file):
                with open(self.state_file) as f:
                    data = json.load(f)
            data["mini"] = [self.x, self.y]
            data["mini_user"] = True
            self.user_set = True
            with open(self.state_file, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    def rect(self):
        return pygame.Rect(self.x, self.y, self.w, self.h)

    def hit(self, pos):
        return inside(pos, self.rect())

    def down(self, pos):
        self.down_at, self.down_pos = time.time(), pos
        self.grab = (pos[0] - self.x, pos[1] - self.y)
        self.dragging = False

    def move(self, pos):
        if self.down_at is None:
            return
        if self.dragging:
            self.x = int(clamp(pos[0] - self.grab[0], 0, self.sw - self.w))
            self.y = int(clamp(pos[1] - self.grab[1], 0, self.sh - self.h))

    def update(self):
        if self.down_at and not self.dragging and time.time() - self.down_at >= 0.5:
            self.dragging = True                     # long press -> picked up

    def up(self, pos):
        """Returns 'moved' | 'double' | 'tap' | None."""
        if self.down_at is None:
            return None
        was_drag, self.down_at = self.dragging, None
        self.dragging = False
        if was_drag:
            self._save()
            return "moved"
        now = time.time()
        if now - self.last_tap < 0.45:
            self.last_tap = 0.0
            return "double"
        self.last_tap = now
        return "tap"

    def draw(self, screen):
        self.face.draw(self.surf)
        r = self.rect()
        if self.dragging:
            pygame.draw.rect(screen, (0, 0, 0), r.inflate(24, 24), border_radius=26)
        screen.blit(self.surf, (r.left, r.top))
        pygame.draw.rect(screen, AMBER if self.dragging else (60, 110, 160), r, width=3, border_radius=8)


# ------------------------------------------------------------- photo screen
def draw_photo(surf, preview, number, flash, label, size):
    w, h = size
    u = h / 600.0
    surf.fill(BG)
    if preview is not None:
        pw, ph = fit(preview.get_size(), w, h)
        surf.blit(pygame.transform.smoothscale(preview, (pw, ph)), ((w - pw) // 2, (h - ph) // 2))
    else:
        t = font(30 * u).render("Camera preview", True, MUTED)
        surf.blit(t, ((w - t.get_width()) // 2, h // 2))
    m, L = 40 * u, 70 * u                                       # viewfinder corners
    for sx, sy in ((m, m), (w - m, m), (m, h - m), (w - m, h - m)):
        dx, dy = (1 if sx < w / 2 else -1), (1 if sy < h / 2 else -1)
        pygame.draw.lines(surf, WHITE, False, [(sx + dx * L, sy), (sx, sy), (sx, sy + dy * L)], 5)
    if number > 0:
        c = (w // 2, int(h * 0.5))
        pygame.draw.circle(surf, (0, 0, 0), c, int(78 * u))
        pygame.draw.circle(surf, AMBER, c, int(78 * u), 6)
        n = font(100 * u).render(str(number), True, WHITE)
        surf.blit(n, (c[0] - n.get_width() // 2, c[1] - n.get_height() // 2))
    t = font(26 * u).render(label, True, WHITE)
    pygame.draw.rect(surf, (0, 0, 0), pygame.Rect(int(w / 2 - t.get_width() / 2 - 16 * u), int(h - 84 * u), int(t.get_width() + 32 * u), int(44 * u)), border_radius=int(14 * u))
    surf.blit(t, (w / 2 - t.get_width() / 2, h - 80 * u))
    if flash:
        surf.fill(WHITE)


# ------------------------------------------------------------------ viewer
class ViewerScreen:
    def __init__(self, size):
        self.w, self.h = size
        self.u = self.h / 600.0
        self.path = None
        self.img = None
        self._scaled = None
        self.timed = False
        self.left = 0.0
        self.total = 10.0
        self.controls = False
        self.hidden = False
        self.index, self.count = 0, 0
        self.confirm_until = 0.0
        self.paused = False

    def open(self, path, timed=False, seconds=10.0, controls=False, hidden=False, index=0, count=1, allow_hide=True, allow_copy=False):
        self.allow_hide = allow_hide
        self.allow_copy = allow_copy
        self.path, self.timed, self.left, self.total = path, timed, seconds, seconds
        self.controls, self.hidden, self.index, self.count = controls, hidden, index, count
        self.img = load_image(path)
        self._scaled = None
        self.confirm_until = 0.0

    def tick(self, dt, paused):
        self.paused = paused
        if self.timed and not paused:
            self.left = max(0.0, self.left - dt)

    def finished(self):
        return self.timed and self.left <= 0

    def _buttons(self):
        u, w, h = self.u, self.w, self.h
        bw, bh, gap = 110 * u, 64 * u, 18 * u
        names = ["prev", "next", "copy", "close"] if getattr(self, "allow_copy", False) else ["prev", "next", "hide", "delete", "close"]
        total = len(names) * bw + (len(names) - 1) * gap
        x0, y = 24 * u, h - bh - 14 * u
        out, x = {}, x0
        for n in names:
            wd = bw * (2.4 if n == "copy" else 1.0)
            out[n] = pygame.Rect(int(x), int(y), int(wd), int(bh))
            x += wd + gap
        return out

    def draw(self, surf):
        u, w, h = self.u, self.w, self.h
        surf.fill((0, 0, 0))
        area_h = h - (100 * u if self.controls else 0)
        if self.img is not None:
            if self._scaled is None:
                self._scaled = pygame.transform.smoothscale(self.img, fit(self.img.get_size(), w, area_h))
            sw, sh = self._scaled.get_size()
            surf.blit(self._scaled, ((w - sw) // 2, (area_h - sh) // 2))
        else:
            t = font(30 * u).render("Cannot open this picture", True, MUTED)
            surf.blit(t, ((w - t.get_width()) // 2, h // 2))
        cap = font(20 * u).render(date_of(self.path) + ("   (%d / %d)" % (self.index + 1, self.count) if self.controls else ""), True, TEXT)
        pygame.draw.rect(surf, (0, 0, 0), pygame.Rect(int(14 * u), int(10 * u), int(cap.get_width() + 24 * u), int(36 * u)), border_radius=int(10 * u))
        surf.blit(cap, (26 * u, 14 * u))
        if self.timed:
            bw = w - 80 * u
            pygame.draw.rect(surf, TRACK, pygame.Rect(int(40 * u), int(h - 36 * u), int(bw), int(10 * u)), border_radius=5)
            fw = int(bw * self.left / self.total)
            if fw > 0:
                pygame.draw.rect(surf, AMBER if self.paused else BLUE,
                                 pygame.Rect(int(40 * u), int(h - 36 * u), fw, int(10 * u)), border_radius=min(5, fw // 2))
            msg = "Paused - release to continue" if self.paused else "Closing in %ds  \u2022  touch & hold to keep looking" % math.ceil(self.left)
            t = font(20 * u).render(msg, True, AMBER if self.paused else TEXT)
            pygame.draw.rect(surf, (0, 0, 0), pygame.Rect(int(w / 2 - t.get_width() / 2 - 14 * u), int(h - 76 * u), int(t.get_width() + 28 * u), int(34 * u)), border_radius=int(10 * u))
            surf.blit(t, (w / 2 - t.get_width() / 2, h - 74 * u))
        if self.controls:
            b = self._buttons()
            s = 22 * u
            for n, r in b.items():
                col = {"hide": PURPLE, "delete": RED, "close": TEXT, "copy": GREEN}.get(n, BLUE)
                if n == "hide" and not getattr(self, "allow_hide", True):
                    col = MUTED
                if n == "delete" and time.time() < self.confirm_until:
                    button(surf, r, RED, mix(CARD, RED, 0.5))
                else:
                    button(surf, r, col)
                cx, cy = r.centerx, r.centery
                if n == "prev":
                    icon_arrow(surf, cx, cy, s, col, True)
                elif n == "next":
                    icon_arrow(surf, cx, cy, s, col, False)
                elif n == "hide":
                    icon_lock(surf, cx, cy - 2 * u, s * 0.8, col, open_=self.hidden)
                elif n == "delete":
                    icon_trash(surf, cx, cy, s * 0.8, col)
                elif n == "copy":
                    t2 = font(20 * u).render("Copy to Gallery", True, col)
                    surf.blit(t2, (cx - t2.get_width() / 2, cy - t2.get_height() / 2))
                else:
                    icon_x(surf, cx, cy, s, col)
            if "hide" in b:
                t = font(16 * u).render("Unhide" if self.hidden else "Hide", True, MUTED)
                surf.blit(t, (b["hide"].centerx - t.get_width() / 2, b["hide"].top - 22 * u))
            if "delete" in b and time.time() < self.confirm_until:
                t = font(16 * u).render("Tap again to delete", True, RED)
                surf.blit(t, (b["delete"].centerx - t.get_width() / 2, b["delete"].top - 22 * u))

    def click(self, pos):
        if not self.controls:
            return None
        for n, r in self._buttons().items():
            if inside(pos, r):
                if n == "hide" and not getattr(self, "allow_hide", True):
                    return None
                if n == "delete":
                    if time.time() < self.confirm_until:
                        return "delete"
                    self.confirm_until = time.time() + 3.0
                    return None
                return n
        return None

    def swipe(self, p0, p1):
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        if self.controls and abs(dx) > 120 * self.u and abs(dy) < 90 * self.u:
            return "next" if dx < 0 else "prev"
        return None


# ----------------------------------------------------------------- gallery
class GalleryScreen:
    """Thumbnail grid for pictures + videos. Also used for hidden gallery, security photos and photo picking."""

    def __init__(self, size):
        self.w, self.h = size
        self.u = self.h / 600.0
        self.hidden = False
        self.files = []
        self.scroll = 0.0
        self.cache = {}
        self.down = None
        self.moved = 0.0
        self.top = 84 * self.u
        self.title = "Gallery"
        self.accent_col = None
        self.select_limit = 0
        self.selected = []
        self.show_lock = True
        self.video_thumb = lambda p: None
        self.captions = False
        self.caption_fn = None

    def open(self, files, hidden=False, title=None, accent=None, select=0, show_lock=True, captions=False):
        self.files, self.hidden, self.scroll = files, hidden, 0.0
        self.title = title or ("Hidden Gallery" if hidden else "Gallery")
        self.accent_col, self.select_limit, self.show_lock, self.captions = accent, select, show_lock, captions
        self.selected = []
        self.cache = {k: v for k, v in self.cache.items() if k in files}

    def _grid(self):
        u = self.u
        margin, gap = 24 * u, 16 * u
        cols = max(2, int(self.w / (250 * u)))
        tw = (self.w - 2 * margin - (cols - 1) * gap) / cols
        th = tw * 0.72
        return margin, gap, cols, tw, th

    def _cell(self, i):
        margin, gap, cols, tw, th = self._grid()
        r, c = divmod(i, cols)
        return pygame.Rect(int(margin + c * (tw + gap)), int(self.top + gap + r * (th + gap) - self.scroll), int(tw), int(th))

    def _max_scroll(self):
        margin, gap, cols, tw, th = self._grid()
        rows = (len(self.files) + cols - 1) // cols
        content = rows * (th + gap) + gap
        return max(0.0, content - (self.h - self.top) + 20 * self.u)

    def action_rect(self):
        u = self.u
        if self.select_limit:
            return pygame.Rect(int(self.w - 190 * u), int(14 * u), int(170 * u), int(56 * u))
        d = 56 * u
        return pygame.Rect(int(self.w - d - 20 * u), int(14 * u), int(d), int(d))

    def _thumb(self, path, budget):
        try:
            mt = os.path.getmtime(path)
        except OSError:
            return None
        hit = self.cache.get(path)
        if hit and hit[0] == mt:
            return hit[1]
        if budget[0] <= 0:
            return None
        budget[0] -= 1
        src = path
        if path.lower().endswith((".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v")):
            src = self.video_thumb(path)
            if not src:
                tile = pygame.Surface((int(self._grid()[3]), int(self._grid()[4])))
                tile.fill((25, 35, 55))
                self.cache[path] = (mt, tile)
                return tile
        img = load_image(src)
        if img is None:
            return None
        _, _, _, tw, th = self._grid()
        iw, ih = img.get_size()
        k = max(tw / iw, th / ih)
        big = pygame.transform.smoothscale(img, (max(1, int(iw * k)), max(1, int(ih * k))))
        tile = pygame.Surface((int(tw), int(th)))
        tile.blit(big, ((int(tw) - big.get_width()) // 2, (int(th) - big.get_height()) // 2))
        self.cache[path] = (mt, tile)
        return tile

    def draw(self, surf):
        u, w, h = self.u, self.w, self.h
        accent = self.accent_col or (PURPLE if self.hidden else BLUE)
        surf.fill(mix(BG, PURPLE, 0.10) if self.hidden else BG)
        budget = [3]
        for i, p in enumerate(self.files):
            r = self._cell(i)
            if r.bottom < self.top or r.top > h:
                continue
            tile = self._thumb(p, budget)
            if tile is not None:
                surf.blit(tile, (r.left, r.top))
            else:
                pygame.draw.rect(surf, CARD, r)
            if p.lower().endswith((".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v")):
                pygame.draw.circle(surf, (0, 0, 0), (r.centerx, r.centery), int(26 * u))
                pygame.draw.polygon(surf, WHITE, [(r.centerx - 8 * u, r.centery - 14 * u), (r.centerx - 8 * u, r.centery + 14 * u), (r.centerx + 16 * u, r.centery)])
            if self.captions:
                cap = self.caption_fn(p) if self.caption_fn else os.path.basename(p)[4:-4].replace("_", " ")
                t = font(14 * u, False).render(cap[:34], True, WHITE)
                pygame.draw.rect(surf, (0, 0, 0), pygame.Rect(r.left, r.bottom - int(24 * u), r.width, int(24 * u)))
                surf.blit(t, (r.left + 6 * u, r.bottom - 21 * u))
            sel = p in self.selected
            pygame.draw.rect(surf, GREEN if sel else mix(CARD, accent, 0.5), r, width=4 if sel else 2, border_radius=6)
            if sel:
                pygame.draw.circle(surf, GREEN, (r.right - int(22 * u), r.top + int(22 * u)), int(15 * u))
                pygame.draw.lines(surf, BG, False, [(r.right - 30 * u, r.top + 22 * u), (r.right - 23 * u, r.top + 29 * u), (r.right - 12 * u, r.top + 15 * u)], 4)
        if not self.files:
            m = "No hidden pictures yet" if self.hidden else "Nothing here yet"
            t = font(32 * u).render(m, True, MUTED)
            surf.blit(t, ((w - t.get_width()) // 2, h * 0.42))
            hint = "Open a picture in the gallery and tap the lock to hide it" if self.hidden else "Say \"Luna, take a selfie\"  or  use the Camera app"
            t = font(20 * u).render(hint, True, MUTED)
            surf.blit(t, ((w - t.get_width()) // 2, h * 0.42 + 50 * u))
        pygame.draw.rect(surf, mix(BG, accent, 0.18), pygame.Rect(0, 0, w, int(self.top)))
        pygame.draw.line(surf, accent, (0, self.top), (w, self.top), 2)
        if self.hidden:
            icon_lock(surf, 118 * u, 44 * u, 18 * u, PURPLE)
        else:
            icon_gallery(surf, 118 * u, 42 * u, 20 * u, accent)
        tw = font(30 * u).render(self.title, True, TEXT)
        surf.blit(tw, (154 * u, 18 * u))
        if self.select_limit:
            cnt = "%d / %d selected" % (len(self.selected), self.select_limit)
        else:
            cnt = "%d item%s" % (len(self.files), "" if len(self.files) == 1 else "s")
        surf.blit(font(19 * u, False).render(cnt, True, MUTED), (154 * u + tw.get_width() + 16 * u, 30 * u))
        ar = self.action_rect()
        if self.select_limit:
            ok = len(self.selected) >= 1
            button(surf, ar, GREEN if ok else MUTED, mix(CARD, GREEN, 0.4) if ok else None)
            t = font(22 * u).render("Use these", True, TEXT)
            surf.blit(t, (ar.centerx - t.get_width() / 2, ar.centery - t.get_height() / 2))
        elif self.show_lock:
            button(surf, ar, PURPLE)
            icon_lock(surf, ar.centerx, ar.centery - 2 * u, 15 * u, PURPLE, open_=self.hidden)
        if self._max_scroll() > 0:
            frac = self.scroll / self._max_scroll()
            bh = 80 * u
            pygame.draw.rect(surf, TRACK, pygame.Rect(w - int(8 * u), int(self.top + 10 + frac * (h - self.top - bh - 20)), int(5 * u), int(bh)), border_radius=3)

    def pointer_down(self, pos):
        self.down, self.moved, self._last = pos, 0.0, pos

    def pointer_move(self, pos):
        if self.down is None:
            return
        dy = pos[1] - self._last[1]
        self.moved += abs(dy) + abs(pos[0] - self._last[0])
        self._last = pos
        if self.moved > 14 * self.u:
            self.scroll = clamp(self.scroll - dy, 0, self._max_scroll())

    def pointer_up(self, pos):
        if self.down is None:
            return None
        self.down = None
        if self.moved > 14 * self.u:
            return None
        ar = self.action_rect()
        if inside(pos, ar) and (self.select_limit or self.show_lock):
            return ("done", list(self.selected)) if self.select_limit else ("lock", None)
        if pos[1] > self.top:
            for i, p in enumerate(self.files):
                if inside(pos, self._cell(i)):
                    if self.select_limit:
                        if p in self.selected:
                            self.selected.remove(p)
                        elif len(self.selected) < self.select_limit:
                            self.selected.append(p)
                        return ("select", len(self.selected))
                    return ("open", i)
        return None


# ------------------------------------------------------------------ PIN pad
class PinPad:
    """On-screen 4-digit keypad. The PIN is typed by touch only - it is never spoken or logged."""

    def __init__(self, size, pins):
        self.w, self.h = size
        self.u = self.h / 600.0
        self.pins = pins
        self.mode = "unlock"
        self.buf = ""
        self.stage = "enter"
        self.first = ""
        self.msg = ""
        self.shake_t = 0.0
        self.pressed = (None, 0.0)
        self.wrong = 0
        self.locked_until = 0.0

    def start(self, mode, pins=None, label=None):
        if pins is not None:
            self.pins = pins
        self.label = label
        self.mode = mode                                     # unlock | setup | change
        self.stage = "verify" if mode in ("unlock", "change") else "new"
        self.buf, self.first, self.msg = "", "", ""

    def title(self):
        lab = getattr(self, "label", None)
        if self.stage == "verify":
            return (lab or "Enter PIN") if self.mode == "unlock" else "Enter current PIN"
        return "Create a 4-digit PIN" if self.stage == "new" else "Confirm your PIN"

    def _keys(self):
        u = self.u
        kw, kh, gap = 104 * u, 66 * u, 14 * u
        x0 = self.w / 2 - (3 * kw + 2 * gap) / 2
        y0 = 238 * u
        labels = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "X", "0", "<"]
        return {lab: pygame.Rect(int(x0 + (i % 3) * (kw + gap)), int(y0 + (i // 3) * (kh + gap)), int(kw), int(kh)) for i, lab in enumerate(labels)}

    def draw(self, surf):
        u, w, h = self.u, self.w, self.h
        surf.fill(mix(BG, PURPLE, 0.12))
        icon_lock(surf, w / 2, 60 * u, 26 * u, PURPLE)
        t = font(30 * u).render(self.title(), True, TEXT)
        surf.blit(t, (w / 2 - t.get_width() / 2, 100 * u))
        now = time.time()
        off = math.sin(now * 60) * 12 * u if now < self.shake_t else 0
        for i in range(4):
            c = (int(w / 2 + (i - 1.5) * 54 * u + off), int(176 * u))
            pygame.draw.circle(surf, PURPLE if i < len(self.buf) else TRACK, c, int(15 * u))
            if i >= len(self.buf):
                pygame.draw.circle(surf, mix(BG, PURPLE, 0.3), c, int(15 * u), 2)
        if now < self.locked_until:
            msg, col = "Too many tries. Wait %ds" % math.ceil(self.locked_until - now), RED
        else:
            msg, col = self.msg, (RED if "wrong" in self.msg.lower() or "match" in self.msg.lower() else MUTED)
        m = font(20 * u).render(msg or "Type the PIN on the keypad", True, col)
        surf.blit(m, (w / 2 - m.get_width() / 2, 202 * u))
        for lab, r in self._keys().items():
            hot = self.pressed[0] == lab and now - self.pressed[1] < 0.15
            button(surf, r, PURPLE if lab not in ("X", "<") else MUTED, mix(CARD, PURPLE, 0.5) if hot else None)
            if lab == "X":
                icon_x(surf, r.centerx, r.centery, 20 * u, MUTED)
            elif lab == "<":
                icon_arrow(surf, r.centerx, r.centery, 20 * u, MUTED, True)
            else:
                n = font(34 * u).render(lab, True, TEXT)
                surf.blit(n, (r.centerx - n.get_width() / 2, r.centery - n.get_height() / 2))

    def hits_key(self, pos):
        return any(inside(pos, r) for r in self._keys().values())

    def tap(self, pos):
        """Returns 'unlocked' | 'pin_set' | 'cancel' | None."""
        now = time.time()
        for lab, r in self._keys().items():
            if not inside(pos, r):
                continue
            self.pressed = (lab, now)
            if now < self.locked_until:
                return None
            if lab == "X":
                return "cancel"
            if lab == "<":
                self.buf = self.buf[:-1]
                return None
            if len(self.buf) < 4:
                self.buf += lab
            if len(self.buf) == 4:
                return self._submit()
        return None

    def _fail(self, msg):
        self.buf, self.msg, self.shake_t = "", msg, time.time() + 0.4

    def _submit(self):
        pin, self.buf = self.buf, ""
        if self.stage == "verify":
            if self.pins.verify(pin):
                self.wrong, self.msg = 0, ""
                if self.mode == "unlock":
                    return "unlocked"
                self.stage = "new"
                return None
            self.wrong += 1
            self._fail("Wrong PIN")
            if self.wrong >= 3:
                self.locked_until = time.time() + 30 * (2 ** min(self.wrong - 3, 4))
            return None
        if self.stage == "new":
            self.first, self.stage, self.msg = pin, "confirm", ""
            return None
        if pin == self.first:
            self.pins.set(pin)
            self.first = ""
            return "pin_set"
        self.stage, self.first = "new", ""
        self._fail("PINs did not match - start again")
        return None
