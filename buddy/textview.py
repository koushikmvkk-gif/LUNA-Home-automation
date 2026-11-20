"""Text / Markdown viewer with read-aloud (for .txt and .md files, e.g. from a USB drive)."""
import logging
import os
import re

import pygame

from .face import font
from .fileapps import speech_chunks
from .screens import AMBER, BG, CARD, GREEN, MUTED, TEXT, button, inside
from .ui import Screen, icon
from .util import clamp, guarded, mix

log = logging.getLogger("textview")
MAX_BYTES = 2_000_000


def md_to_lines(raw):
    """Very small Markdown clean-up for display: (text, style) with style in h1/h2/h3/body/code."""
    out, in_code = [], False
    for ln in raw.splitlines():
        if ln.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            out.append((ln, "code"))
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", ln)
        if m:
            out.append((m.group(2).strip(), "h%d" % len(m.group(1))))
            continue
        ln = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", ln)
        ln = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", ln)
        ln = re.sub(r"(\*\*|__|\*|_|`)", "", ln)
        ln = re.sub(r"^\s*[-*+]\s+", "\u2022 ", ln)
        out.append((ln, "body"))
    return out


class TextScreen(Screen):
    name, title, accent = "textview", "Text", (110, 200, 255)
    mini_pos = "tr"

    def enter(self, path="", **kw):
        self.path = path
        self.title = os.path.basename(path)[:40]
        self.scale = 1.0
        self.scroll, self.drag, self.moved = 0.0, None, 0.0
        self.reading, self.chunks = False, []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read(MAX_BYTES)
        except OSError as e:
            raw = "Cannot open this file: %s" % e
        self.is_md = path.lower().endswith(".md")
        self.raw = raw
        self.src = md_to_lines(raw) if self.is_md else [(l, "body") for l in raw.splitlines()]
        self._wrap_cache = None

    def leave(self):
        self.stop_reading()

    # ---------------------------------------------------------------- layout
    def _wrapped(self):
        key = (round(self.scale, 2), self.w)
        if self._wrap_cache and self._wrap_cache[0] == key:
            return self._wrap_cache[1]
        u, maxw = self.u, self.w - 80 * self.u
        lines = []
        for text, style in self.src:
            size = {"h1": 34, "h2": 30, "h3": 26, "code": 20}.get(style, 24) * self.scale
            f = font(size * u, style.startswith("h"))
            words, cur = text.split(" "), ""
            if not text.strip():
                lines.append(("", style, size))
                continue
            for wd in words:
                t = (cur + " " + wd).strip() if cur else wd
                if f.render(t, True, TEXT).get_width() > maxw and cur:
                    lines.append((cur, style, size))
                    cur = wd
                else:
                    cur = t
            lines.append((cur, style, size))
        self._wrap_cache = (key, lines)
        return lines

    def _height(self):
        return sum(s * 1.35 * self.u for _, _, s in self._wrapped()) + 40 * self.u

    def _view(self):
        u = self.u
        return pygame.Rect(0, int(78 * u), self.w, int(self.h - 78 * u - 84 * u))

    def _bar(self):
        u = self.u
        y = self.h - 76 * u
        out, x = {}, 30 * u
        for n, s in (("smaller", 64), ("bigger", 64), ("top", 110), ("read", 170)):
            out[n] = pygame.Rect(int(x), int(y), int(s * u), int(64 * u))
            x += s * u + 14 * u
        return out

    @guarded("draw")
    def draw(self, surf):
        u = self.u
        surf.fill((22, 26, 36))
        v = self._view()
        self.scroll = clamp(self.scroll, 0, max(0.0, self._height() - v.height))
        y = v.top + 14 * u - self.scroll
        for text, style, size in self._wrapped():
            h = size * 1.35 * u
            if y + h >= v.top and y <= v.bottom and text:
                col = {"h1": (130, 200, 255), "h2": (150, 215, 255), "h3": (170, 225, 255), "code": (160, 230, 170)}.get(style, TEXT)
                img = font(size * u, style.startswith("h")).render(text, True, col)
                surf.blit(img, (40 * u, y))
            y += h
        self.topbar(surf, self.title)
        pygame.draw.rect(surf, mix(BG, self.accent, 0.12), pygame.Rect(0, int(self.h - 84 * u), self.w, int(84 * u)))
        pygame.draw.line(surf, self.accent, (0, int(self.h - 84 * u)), (self.w, int(self.h - 84 * u)), 2)
        for n, r in self._bar().items():
            on = n == "read" and self.reading
            button(surf, r, GREEN if on else MUTED, mix(CARD, GREEN, 0.4) if on else None)
            if n in ("smaller", "bigger"):
                self.text(surf, "A-" if n == "smaller" else "A+", r.centerx, r.centery - 12 * u, 22, TEXT, center=True)
            elif n == "top":
                self.text(surf, "Top", r.centerx, r.centery - 12 * u, 20, TEXT, center=True)
            else:
                icon(surf, "speaker", r.left + 38 * u, r.centery, 16 * u, GREEN if on else TEXT)
                self.text(surf, "Stop" if on else "Read aloud", r.left + 66 * u, r.centery - 11 * u, 18, TEXT)

    # ---------------------------------------------------------------- input
    def on_down(self, pos):
        self.drag, self.dstart, self.moved = pos, pos, 0.0

    def on_move(self, pos):
        if self.drag is None:
            return
        dy = pos[1] - self.drag[1]
        self.moved += abs(dy)
        self.drag = pos
        self.scroll -= dy

    def on_up(self, pos):
        if self.drag is None:
            return
        start, self.drag = self.dstart, None
        for n, r in self._bar().items():
            if inside(pos, r) and inside(start, r):
                self._press(n)
                return

    def _press(self, n):
        if n in ("smaller", "bigger"):
            self.scale = clamp(self.scale + (0.15 if n == "bigger" else -0.15), 0.7, 2.0)
            self._wrap_cache = None
        elif n == "top":
            self.scroll = 0.0
        elif n == "read":
            self.stop_reading() if self.reading else self.start_reading()

    # ---------------------------------------------------------------- read aloud
    def start_reading(self):
        text = "\n".join(t for t, _ in self.src)
        self.chunks = speech_chunks(text, self.app.cfg.PDF_READ_CHARS)
        self.reading = bool(self.chunks)
        if not self.chunks:
            self.app.speaker.say("This file has no text I can read.")

    def stop_reading(self):
        if self.reading:
            self.reading, self.chunks = False, []
            self.app.speaker.stop_now()

    def tick(self, dt):
        if not self.reading:
            return
        sp = self.app.speaker
        if sp.busy():
            return
        if self.chunks:
            sp.say(self.chunks.pop(0))
        else:
            self.reading = False
            sp.say("That is the end of the file.")

    def context(self):
        return "A text viewer showing '%s'." % self.title

    def comment(self):
        return "Say, Luna, read aloud, and I will read this file to you."
