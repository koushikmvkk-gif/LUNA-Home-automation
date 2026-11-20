"""UI toolkit: Screen base class, icons, list / slider widgets, on-screen keyboard, confirm dialog."""
import math
import time

import pygame

from .face import font
from .screens import (AMBER, BG, BLUE, CARD, GREEN, MUTED, PURPLE, RED, TEXT, TRACK, WHITE, button, icon_arrow, icon_gallery,
                      icon_lock, icon_trash, icon_x, inside)
from .util import clamp, mix


# ----------------------------------------------------------------------------- icons
def _lines(surf, col, pts, w, closed=False):
    pygame.draw.lines(surf, col, closed, pts, max(2, int(w)))


def ic_menu(surf, cx, cy, s, col):
    for k in (-1, 0, 1):
        pygame.draw.rect(surf, col, pygame.Rect(int(cx - s * 0.8), int(cy + k * s * 0.5 - s * 0.09), int(s * 1.6), max(3, int(s * 0.18))), border_radius=3)


def ic_gear(surf, cx, cy, s, col):
    for k in range(8):
        a = math.pi * k / 4
        pygame.draw.line(surf, col, (cx + math.cos(a) * s * 0.7, cy + math.sin(a) * s * 0.7), (cx + math.cos(a) * s * 1.0, cy + math.sin(a) * s * 1.0), max(3, int(s * 0.32)))
    pygame.draw.circle(surf, col, (int(cx), int(cy)), int(s * 0.75))
    pygame.draw.circle(surf, BG, (int(cx), int(cy)), int(s * 0.32))


def ic_music(surf, cx, cy, s, col):
    pygame.draw.circle(surf, col, (int(cx - s * 0.45), int(cy + s * 0.55)), int(s * 0.32))
    pygame.draw.circle(surf, col, (int(cx + s * 0.5), int(cy + s * 0.35)), int(s * 0.32))
    pygame.draw.line(surf, col, (cx - s * 0.2, cy + s * 0.5), (cx - s * 0.2, cy - s * 0.7), max(3, int(s * 0.15)))
    pygame.draw.line(surf, col, (cx + s * 0.75, cy + s * 0.3), (cx + s * 0.75, cy - s * 0.9), max(3, int(s * 0.15)))
    pygame.draw.polygon(surf, col, [(cx - s * 0.2, cy - s * 0.7), (cx + s * 0.75, cy - s * 0.95), (cx + s * 0.75, cy - s * 0.6), (cx - s * 0.2, cy - s * 0.35)])


def ic_film(surf, cx, cy, s, col):
    pygame.draw.rect(surf, col, pygame.Rect(int(cx - s), int(cy - s * 0.7), int(2 * s), int(1.4 * s)), width=max(3, int(s * 0.14)), border_radius=int(s * 0.15))
    for k in (-1, 1):
        for j in range(3):
            pygame.draw.rect(surf, col, pygame.Rect(int(cx + k * s * 0.78 - s * 0.07), int(cy - s * 0.5 + j * s * 0.45), int(s * 0.14), int(s * 0.25)))
    pygame.draw.polygon(surf, col, [(cx - s * 0.2, cy - s * 0.3), (cx - s * 0.2, cy + s * 0.3), (cx + s * 0.3, cy)])


def ic_chart(surf, cx, cy, s, col):
    for k, hgt in enumerate((0.5, 1.0, 0.75, 1.3)):
        pygame.draw.rect(surf, col, pygame.Rect(int(cx - s + k * s * 0.55), int(cy + s * 0.7 - hgt * s), int(s * 0.38), int(hgt * s)), border_radius=3)


def ic_camera(surf, cx, cy, s, col):
    pygame.draw.rect(surf, col, pygame.Rect(int(cx - s), int(cy - s * 0.55), int(2 * s), int(1.4 * s)), border_radius=int(s * 0.2))
    pygame.draw.rect(surf, col, pygame.Rect(int(cx - s * 0.4), int(cy - s * 0.85), int(s * 0.8), int(s * 0.4)), border_radius=4)
    pygame.draw.circle(surf, BG, (int(cx), int(cy + s * 0.15)), int(s * 0.5))
    pygame.draw.circle(surf, col, (int(cx), int(cy + s * 0.15)), int(s * 0.32))


def ic_pencil(surf, cx, cy, s, col):
    pygame.draw.polygon(surf, col, [(cx + s * 0.85, cy - s * 0.85), (cx + s * 1.0, cy - s * 0.55), (cx - s * 0.3, cy + s * 0.75), (cx - s * 0.7, cy + s * 0.9), (cx - s * 0.55, cx * 0 + cy + s * 0.45)])
    pygame.draw.polygon(surf, col, [(cx + s * 0.6, cy - s * 1.0), (cx + s * 0.95, cy - s * 0.8), (cx + s * 0.8, cy - s * 0.6), (cx + s * 0.5, cy - s * 0.85)])


def ic_info(surf, cx, cy, s, col):
    pygame.draw.circle(surf, col, (int(cx), int(cy)), int(s), max(3, int(s * 0.14)))
    pygame.draw.circle(surf, col, (int(cx), int(cy - s * 0.45)), max(2, int(s * 0.11)))
    pygame.draw.line(surf, col, (cx, cy - s * 0.15), (cx, cy + s * 0.55), max(3, int(s * 0.16)))


def ic_wifi(surf, cx, cy, s, col):
    for k, r in enumerate((0.45, 0.85, 1.25)):
        pts = [(cx + math.cos(math.radians(a)) * s * r, cy + s * 0.7 - math.sin(math.radians(a)) * s * r) for a in range(40, 141, 10)]
        _lines(surf, col, pts, s * 0.16)
    pygame.draw.circle(surf, col, (int(cx), int(cy + s * 0.7)), max(2, int(s * 0.13)))


def ic_bluetooth(surf, cx, cy, s, col):
    pts = [(cx - s * 0.5, cy - s * 0.5), (cx + s * 0.5, cy + s * 0.5), (cx, cy + s * 1.0), (cx, cy - s * 1.0), (cx + s * 0.5, cy - s * 0.5), (cx - s * 0.5, cy + s * 0.5)]
    _lines(surf, col, pts, s * 0.16)


def ic_sun(surf, cx, cy, s, col):
    pygame.draw.circle(surf, col, (int(cx), int(cy)), int(s * 0.45))
    for k in range(8):
        a = math.pi * k / 4
        pygame.draw.line(surf, col, (cx + math.cos(a) * s * 0.7, cy + math.sin(a) * s * 0.7), (cx + math.cos(a) * s * 1.0, cy + math.sin(a) * s * 1.0), max(2, int(s * 0.14)))


def ic_power(surf, cx, cy, s, col):
    pts = [(cx + math.cos(math.radians(a)) * s * 0.85, cy - math.sin(math.radians(a)) * s * 0.85) for a in range(-50, 231, 10)]
    _lines(surf, col, pts, s * 0.18)
    pygame.draw.line(surf, col, (cx, cy - s * 1.0), (cx, cy), max(3, int(s * 0.18)))


def ic_shield(surf, cx, cy, s, col):
    pygame.draw.polygon(surf, col, [(cx - s * 0.8, cy - s * 0.8), (cx + s * 0.8, cy - s * 0.8), (cx + s * 0.8, cy + s * 0.1), (cx, cy + s * 1.0), (cx - s * 0.8, cy + s * 0.1)])
    _lines(surf, BG, [(cx - s * 0.35, cy), (cx - s * 0.05, cy + s * 0.3), (cx + s * 0.4, cy - s * 0.3)], s * 0.16)


def ic_plus(surf, cx, cy, s, col):
    t = max(3, int(s * 0.25))
    pygame.draw.line(surf, col, (cx - s * 0.7, cy), (cx + s * 0.7, cy), t)
    pygame.draw.line(surf, col, (cx, cy - s * 0.7), (cx, cy + s * 0.7), t)


def ic_play(surf, cx, cy, s, col):
    pygame.draw.polygon(surf, col, [(cx - s * 0.5, cy - s * 0.7), (cx - s * 0.5, cy + s * 0.7), (cx + s * 0.7, cy)])


def ic_pause(surf, cx, cy, s, col):
    for k in (-1, 1):
        pygame.draw.rect(surf, col, pygame.Rect(int(cx + k * s * 0.38 - s * 0.17), int(cy - s * 0.65), int(s * 0.34), int(s * 1.3)), border_radius=3)


def ic_next(surf, cx, cy, s, col, flip=False):
    d = -1 if flip else 1
    pygame.draw.polygon(surf, col, [(cx - d * s * 0.7, cy - s * 0.6), (cx - d * s * 0.7, cy + s * 0.6), (cx + d * s * 0.3, cy)])
    pygame.draw.rect(surf, col, pygame.Rect(int(cx + d * s * 0.4 - (s * 0.12 if d > 0 else 0) - (s * 0.12 if d < 0 else 0)), int(cy - s * 0.6), int(s * 0.24), int(s * 1.2)))


def ic_seek(surf, cx, cy, s, col, back=False):
    d = -1 if back else 1
    for k in (0, 1):
        x = cx + d * (k * s * 0.7 - s * 0.35)
        pygame.draw.polygon(surf, col, [(x - d * s * 0.4, cy - s * 0.55), (x - d * s * 0.4, cy + s * 0.55), (x + d * s * 0.4, cy)])


def ic_loop(surf, cx, cy, s, col, one=False):
    pts = [(cx + math.cos(math.radians(a)) * s * 0.8, cy - math.sin(math.radians(a)) * s * 0.6) for a in range(20, 341, 15)]
    _lines(surf, col, pts, s * 0.16)
    pygame.draw.polygon(surf, col, [(cx + s * 0.95, cy - s * 0.3), (cx + s * 0.5, cy - s * 0.55), (cx + s * 0.95, cy - s * 0.85)])
    if one:
        t = font(s * 0.9).render("1", True, col)
        surf.blit(t, (cx - t.get_width() / 2, cy - t.get_height() / 2))


def ic_shuffle(surf, cx, cy, s, col):
    _lines(surf, col, [(cx - s * 0.9, cy - s * 0.5), (cx - s * 0.2, cy - s * 0.5), (cx + s * 0.4, cy + s * 0.5), (cx + s * 0.8, cy + s * 0.5)], s * 0.15)
    _lines(surf, col, [(cx - s * 0.9, cy + s * 0.5), (cx - s * 0.2, cy + s * 0.5), (cx + s * 0.4, cy - s * 0.5), (cx + s * 0.8, cy - s * 0.5)], s * 0.15)


def ic_check(surf, cx, cy, s, col):
    _lines(surf, col, [(cx - s * 0.7, cy), (cx - s * 0.2, cy + s * 0.55), (cx + s * 0.8, cy - s * 0.6)], s * 0.25)


def ic_user(surf, cx, cy, s, col):
    pygame.draw.circle(surf, col, (int(cx), int(cy - s * 0.35)), int(s * 0.4))
    pygame.draw.ellipse(surf, col, pygame.Rect(int(cx - s * 0.8), int(cy + s * 0.15), int(s * 1.6), int(s * 1.0)))


def ic_eye(surf, cx, cy, s, col, off=False):
    pygame.draw.ellipse(surf, col, pygame.Rect(int(cx - s), int(cy - s * 0.5), int(2 * s), int(s)), max(2, int(s * 0.14)))
    pygame.draw.circle(surf, col, (int(cx), int(cy)), int(s * 0.25))
    if off:
        pygame.draw.line(surf, col, (cx - s, cy + s * 0.6), (cx + s, cy - s * 0.6), max(2, int(s * 0.14)))


def ic_eraser(surf, cx, cy, s, col):
    pygame.draw.rect(surf, col, pygame.Rect(int(cx - s * 0.9), int(cy - s * 0.4), int(s * 1.8), int(s * 0.9)), border_radius=int(s * 0.2))
    pygame.draw.rect(surf, (255, 150, 170), pygame.Rect(int(cx - s * 0.9), int(cy - s * 0.4), int(s * 0.7), int(s * 0.9)), border_radius=int(s * 0.2))


def ic_undo(surf, cx, cy, s, col, redo=False):
    d = -1 if redo else 1
    pts = [(cx + d * math.cos(math.radians(a)) * s * 0.7, cy - math.sin(math.radians(a)) * s * 0.55 + s * 0.1) for a in range(-20, 181, 15)]
    _lines(surf, col, pts, s * 0.16)
    pygame.draw.polygon(surf, col, [(cx + d * s * 0.9, cy - s * 0.1), (cx + d * s * 0.45, cy - s * 0.15), (cx + d * s * 0.75, cy + s * 0.35)])


def ic_save(surf, cx, cy, s, col):
    pygame.draw.rect(surf, col, pygame.Rect(int(cx - s * 0.8), int(cy - s * 0.8), int(s * 1.6), int(s * 1.6)), border_radius=int(s * 0.15))
    pygame.draw.rect(surf, BG, pygame.Rect(int(cx - s * 0.45), int(cy - s * 0.8), int(s * 0.9), int(s * 0.5)))
    pygame.draw.rect(surf, BG, pygame.Rect(int(cx - s * 0.5), int(cy + s * 0.1), int(s * 1.0), int(s * 0.7)), border_radius=3)


def ic_video(surf, cx, cy, s, col):
    pygame.draw.rect(surf, col, pygame.Rect(int(cx - s), int(cy - s * 0.55), int(s * 1.45), int(s * 1.1)), border_radius=int(s * 0.18))
    pygame.draw.polygon(surf, col, [(cx + s * 0.55, cy - s * 0.2), (cx + s * 1.0, cy - s * 0.55), (cx + s * 1.0, cy + s * 0.55), (cx + s * 0.55, cy + s * 0.2)])


def ic_refresh(surf, cx, cy, s, col):
    pts = [(cx + math.cos(math.radians(a)) * s * 0.75, cy - math.sin(math.radians(a)) * s * 0.75) for a in range(30, 321, 15)]
    _lines(surf, col, pts, s * 0.17)
    pygame.draw.polygon(surf, col, [(cx + s * 0.95, cy - s * 0.1), (cx + s * 0.35, cy - s * 0.1), (cx + s * 0.75, cy - s * 0.65)])


def ic_folder(surf, cx, cy, s, col):
    pygame.draw.rect(surf, col, pygame.Rect(int(cx - s), int(cy - s * 0.55), int(s * 0.9), int(s * 0.3)), border_radius=3)
    pygame.draw.rect(surf, col, pygame.Rect(int(cx - s), int(cy - s * 0.35), int(2 * s), int(s * 1.0)), border_radius=int(s * 0.15))


def ic_file(surf, cx, cy, s, col):
    pygame.draw.polygon(surf, col, [(cx - s * 0.7, cy - s), (cx + s * 0.25, cy - s), (cx + s * 0.7, cy - s * 0.5), (cx + s * 0.7, cy + s), (cx - s * 0.7, cy + s)])
    for k in range(3):
        pygame.draw.line(surf, BG, (cx - s * 0.4, cy - s * 0.1 + k * s * 0.35), (cx + s * 0.4, cy - s * 0.1 + k * s * 0.35), max(2, int(s * 0.1)))


def ic_pdf(surf, cx, cy, s, col):
    ic_file(surf, cx, cy, s, col)
    t = font(s * 0.62).render("PDF", True, BG)
    surf.blit(t, (cx - t.get_width() / 2, cy + s * 0.1))


def ic_usb(surf, cx, cy, s, col):
    pygame.draw.rect(surf, col, pygame.Rect(int(cx - s * 0.55), int(cy - s * 0.2), int(s * 1.1), int(s * 1.1)), border_radius=int(s * 0.15))
    pygame.draw.rect(surf, col, pygame.Rect(int(cx - s * 0.3), int(cy - s * 0.95), int(s * 0.6), int(s * 0.8)))
    pygame.draw.rect(surf, BG, pygame.Rect(int(cx - s * 0.18), int(cy - s * 0.8), int(s * 0.12), int(s * 0.3)))
    pygame.draw.rect(surf, BG, pygame.Rect(int(cx + s * 0.06), int(cy - s * 0.8), int(s * 0.12), int(s * 0.3)))


def ic_book(surf, cx, cy, s, col):
    pygame.draw.rect(surf, col, pygame.Rect(int(cx - s), int(cy - s * 0.7), int(s * 0.95), int(s * 1.4)), border_radius=int(s * 0.1))
    pygame.draw.rect(surf, col, pygame.Rect(int(cx + s * 0.05), int(cy - s * 0.7), int(s * 0.95), int(s * 1.4)), border_radius=int(s * 0.1))
    for k in range(3):
        pygame.draw.line(surf, BG, (cx - s * 0.8, cy - s * 0.3 + k * s * 0.3), (cx - s * 0.25, cy - s * 0.3 + k * s * 0.3), max(2, int(s * 0.08)))
        pygame.draw.line(surf, BG, (cx + s * 0.25, cy - s * 0.3 + k * s * 0.3), (cx + s * 0.8, cy - s * 0.3 + k * s * 0.3), max(2, int(s * 0.08)))


def ic_speaker(surf, cx, cy, s, col, off=False):
    pygame.draw.polygon(surf, col, [(cx - s * 0.9, cy - s * 0.35), (cx - s * 0.4, cy - s * 0.35), (cx + s * 0.1, cy - s * 0.8), (cx + s * 0.1, cy + s * 0.8), (cx - s * 0.4, cy + s * 0.35), (cx - s * 0.9, cy + s * 0.35)])
    for r in (0.5, 0.9):
        pts = [(cx + s * 0.1 + math.cos(math.radians(a)) * s * r, cy - math.sin(math.radians(a)) * s * r) for a in range(-40, 41, 10)]
        _lines(surf, col, pts, s * 0.12)
    if off:
        pygame.draw.line(surf, RED, (cx - s, cy + s * 0.9), (cx + s, cy - s * 0.9), max(3, int(s * 0.16)))


def ic_zoom(surf, cx, cy, s, col, plus=True):
    pygame.draw.circle(surf, col, (int(cx - s * 0.15), int(cy - s * 0.15)), int(s * 0.65), max(2, int(s * 0.14)))
    pygame.draw.line(surf, col, (cx + s * 0.3, cy + s * 0.3), (cx + s * 0.9, cy + s * 0.9), max(3, int(s * 0.2)))
    pygame.draw.line(surf, col, (cx - s * 0.45, cy - s * 0.15), (cx + s * 0.15, cy - s * 0.15), max(2, int(s * 0.12)))
    if plus:
        pygame.draw.line(surf, col, (cx - s * 0.15, cy - s * 0.45), (cx - s * 0.15, cy + s * 0.15), max(2, int(s * 0.12)))


def ic_calendar(surf, cx, cy, s, col):
    pygame.draw.rect(surf, col, pygame.Rect(int(cx - s), int(cy - s * 0.8), int(2 * s), int(1.8 * s)), width=max(3, int(s * 0.14)), border_radius=int(s * 0.2))
    pygame.draw.rect(surf, col, pygame.Rect(int(cx - s), int(cy - s * 0.8), int(2 * s), int(s * 0.5)), border_top_left_radius=int(s * 0.2), border_top_right_radius=int(s * 0.2))
    for k in (-1, 1):
        pygame.draw.line(surf, col, (cx + k * s * 0.5, cy - s * 1.0), (cx + k * s * 0.5, cy - s * 0.6), max(3, int(s * 0.14)))
    for r in range(2):
        for c in range(3):
            pygame.draw.rect(surf, col, pygame.Rect(int(cx - s * 0.7 + c * s * 0.5), int(cy - s * 0.05 + r * s * 0.45), int(s * 0.3), int(s * 0.28)), border_radius=2)


def ic_control(surf, cx, cy, s, col):
    """Wall switch + ESP32 chip: a rocker switch plate with Wi-Fi arcs."""
    pygame.draw.rect(surf, col, pygame.Rect(int(cx - s * 0.55), int(cy - s * 0.2), int(s * 1.1), int(s * 1.25)), width=max(3, int(s * 0.14)), border_radius=int(s * 0.18))
    pygame.draw.rect(surf, col, pygame.Rect(int(cx - s * 0.25), int(cy + s * 0.05), int(s * 0.5), int(s * 0.55)), border_radius=int(s * 0.1))
    for r in (0.45, 0.85):
        pts = [(cx + math.cos(math.radians(a)) * s * r, cy - s * 0.35 - math.sin(math.radians(a)) * s * r) for a in range(40, 141, 10)]
        _lines(surf, col, pts, s * 0.14)


ICONS = {"calendar": ic_calendar, "control": ic_control, "folder": ic_folder, "file": ic_file, "pdf": ic_pdf, "usb": ic_usb, "book": ic_book, "speaker": ic_speaker, "menu": ic_menu, "gear": ic_gear, "music": ic_music, "film": ic_film, "chart": ic_chart, "camera": ic_camera, "pencil": ic_pencil,
         "info": ic_info, "wifi": ic_wifi, "bluetooth": ic_bluetooth, "sun": ic_sun, "power": ic_power, "shield": ic_shield, "plus": ic_plus,
         "play": ic_play, "pause": ic_pause, "check": ic_check, "user": ic_user, "shuffle": ic_shuffle, "eraser": ic_eraser, "save": ic_save,
         "video": ic_video, "refresh": ic_refresh, "gallery": icon_gallery, "lock": icon_lock, "trash": icon_trash, "x": icon_x}


def icon(surf, name, cx, cy, s, col, **kw):
    fn = ICONS.get(name)
    if fn:
        fn(surf, cx, cy, s, col, **kw)


# ----------------------------------------------------------------------------- Screen base
class Screen:
    name = "screen"
    title = ""
    mini = True            # draw the minimised Luna face on top
    has_back = True
    accent = BLUE
    mini_pos = "br"       # default corner for the minimised Luna (tl / tr / bl / br)

    def __init__(self, app):
        self.app = app
        self.w, self.h = app.size
        self.u = self.h / 600.0
        self._back_down = False

    # lifecycle
    def enter(self, **kw):
        pass

    def leave(self):
        pass

    def tick(self, dt):
        pass

    def draw(self, surf):
        pass

    # input (hooks)
    def on_down(self, pos):
        pass

    def on_move(self, pos):
        pass

    def on_up(self, pos):
        pass

    def on_back(self):
        self.app.back()

    def priority_hit(self, pos):
        """True when `pos` is on a control that must win over the mini face drawn on top."""
        return False

    def context(self):
        return "The %s screen." % (self.title or self.name)

    def comment(self):
        return ""

    # input (framework)
    def back_rect(self):
        u = self.u
        return pygame.Rect(int(14 * u), int(10 * u), int(60 * u), int(56 * u))

    def down(self, pos):
        if self.has_back and inside(pos, self.back_rect()):
            self._back_down = True
            return
        self.on_down(pos)

    def move(self, pos):
        if not self._back_down:
            self.on_move(pos)

    def up(self, pos):
        if self._back_down:
            self._back_down = False
            if inside(pos, self.back_rect()):
                self.on_back()
            return
        self.on_up(pos)

    # drawing helpers
    def topbar(self, surf, title=None, right=None, accent=None):
        u, w = self.u, self.w
        acc = accent or self.accent
        pygame.draw.rect(surf, mix(BG, acc, 0.16), pygame.Rect(0, 0, w, int(78 * u)))
        pygame.draw.line(surf, acc, (0, int(78 * u)), (w, int(78 * u)), 2)
        if self.has_back:
            r = self.back_rect()
            button(surf, r, TEXT)
            icon_arrow(surf, r.centerx, r.centery, 18 * u, TEXT, True)
        t = font(30 * u).render(title or self.title, True, TEXT)
        surf.blit(t, (92 * u, 22 * u))
        if right:
            r = font(20 * u).render(right, True, MUTED)
            surf.blit(r, (w - r.get_width() - 24 * u, 30 * u))

    def text(self, surf, msg, x, y, size=20, col=TEXT, bold=True, center=False, maxw=None):
        img = font(size * self.u, bold).render(msg, True, col)
        if maxw and img.get_width() > maxw:
            while len(msg) > 3 and font(size * self.u, bold).render(msg + "...", True, col).get_width() > maxw:
                msg = msg[:-1]
            img = font(size * self.u, bold).render(msg + "...", True, col)
        surf.blit(img, (x - img.get_width() / 2 if center else x, y))
        return img.get_width()


# ----------------------------------------------------------------------------- widgets
class ListView:
    """Scrollable list. rows: dicts with label, sub, right, col, icon, tag. Tap returns the row's tag."""

    def __init__(self, u):
        self.u = u
        self.rows = []
        self.scroll = 0.0
        self.row_h = 76 * u
        self.down_pos = None
        self.moved = 0.0
        self._last = None
        self.rect = pygame.Rect(0, 0, 10, 10)

    def set_rows(self, rows, keep=False):
        self.rows = rows
        if not keep:
            self.scroll = 0.0
        self.scroll = clamp(self.scroll, 0, self.max_scroll())

    def max_scroll(self):
        return max(0.0, len(self.rows) * self.row_h - self.rect.height + 10 * self.u)

    def draw(self, surf, rect, accent=BLUE):
        self.rect = rect
        u = self.u
        for i, r in enumerate(self.rows):
            y = rect.top + i * self.row_h - self.scroll
            if y + self.row_h < rect.top or y > rect.bottom:
                continue
            cell = pygame.Rect(rect.left, int(y), rect.width, int(self.row_h - 8 * u))
            if cell.top < rect.top - 4 or cell.bottom > rect.bottom + 4:
                continue
            col = r.get("col", accent)
            pygame.draw.rect(surf, mix(CARD, col, 0.10) if r.get("hl") else CARD, cell, border_radius=int(14 * u))
            pygame.draw.rect(surf, mix(CARD, col, 0.45), cell, width=2, border_radius=int(14 * u))
            x = cell.left + 20 * u
            if r.get("icon"):
                icon(surf, r["icon"], cell.left + 40 * u, cell.centery, 20 * u, col)
                x = cell.left + 80 * u
            sub = r.get("sub")
            lab = font(24 * u).render(r["label"], True, TEXT)
            ty = cell.centery - lab.get_height() / 2 - (10 * u if sub else 0)
            surf.blit(lab, (x, ty))
            if sub:
                s = font(17 * u, False).render(sub, True, MUTED)
                surf.blit(s, (x, ty + lab.get_height() + 1))
            if r.get("right"):
                rt = font(20 * u).render(r["right"], True, r.get("rcol", MUTED))
                surf.blit(rt, (cell.right - rt.get_width() - 20 * u, cell.centery - rt.get_height() / 2))

    def down(self, pos):
        self.down_pos, self._last, self.moved = pos, pos, 0.0
        self.down_time = time.time()

    def move(self, pos):
        if self.down_pos is None:
            return
        dy = pos[1] - self._last[1]
        self.moved += abs(dy) + abs(pos[0] - self._last[0])
        self._last = pos
        if self.moved > 14 * self.u:
            self.scroll = clamp(self.scroll - dy, 0, self.max_scroll())

    def up(self, pos):
        if self.down_pos is None:
            return None
        self.down_pos = None
        self.last_hold = time.time() - getattr(self, "down_time", time.time())
        if self.moved > 14 * self.u or not inside(pos, self.rect):
            return None
        i = int((pos[1] - self.rect.top + self.scroll) // self.row_h)
        if 0 <= i < len(self.rows):
            return self.rows[i].get("tag", i)
        return None


class Slider:
    def __init__(self, u):
        self.u = u
        self.rect = pygame.Rect(0, 0, 10, 10)
        self.value = 0.5
        self.drag = False

    def draw(self, surf, rect, col=BLUE):
        self.rect = rect
        u = self.u
        track = pygame.Rect(rect.left, rect.centery - int(7 * u), rect.width, int(14 * u))
        pygame.draw.rect(surf, TRACK, track, border_radius=int(7 * u))
        fw = int(rect.width * self.value)
        if fw > 2:
            pygame.draw.rect(surf, col, pygame.Rect(track.left, track.top, fw, track.height), border_radius=min(int(7 * u), fw // 2))
        pygame.draw.circle(surf, TEXT, (rect.left + fw, rect.centery), int(18 * u))
        pygame.draw.circle(surf, col, (rect.left + fw, rect.centery), int(18 * u), 3)

    def down(self, pos):
        if inside(pos, self.rect.inflate(int(40 * self.u), int(50 * self.u))):
            self.drag = True
            return self._set(pos)
        return None

    def move(self, pos):
        return self._set(pos) if self.drag else None

    def up(self, pos):
        was, self.drag = self.drag, False
        return was

    def _set(self, pos):
        self.value = clamp((pos[0] - self.rect.left) / float(self.rect.width), 0.0, 1.0)
        return self.value


# ----------------------------------------------------------------------------- keyboard
class KeyboardScreen(Screen):
    name = "keyboard"
    mini = False          # the keys need the whole screen

    def __init__(self, app):
        super().__init__(app)
        self.text_val = ""
        self.page = "abc"
        self.shift = False
        self.password = False
        self.show = False
        self.cb = None
        self.prompt = ""
        self.hint = ""
        self.maxlen = 64
        self.pressed = (None, 0.0)

    def enter(self, title="", initial="", password=False, cb=None, hint="", maxlen=64, **kw):
        self.prompt, self.text_val, self.password, self.cb, self.hint, self.maxlen = title, initial, password, cb, hint, maxlen
        self.page, self.shift, self.show = "abc", False, False
        self.title = title

    def on_back(self):
        cb = self.cb
        self.app.back()
        if cb:
            cb(None)

    def _rows(self):
        digits = "1234567890"
        if self.page == "sym":
            r2, r3, r4 = "@#$%&-+()/", "_:;!?,.'\"=", "*<>{}[]|\\^~"
            return [list(digits), list(r2), list(r3), list(r4)]
        letters = ["qwertyuiop", "asdfghjkl", "zxcvbnm"]
        if self.shift:
            letters = [x.upper() for x in letters]
        return [list(digits)] + [list(x) for x in letters]

    def _layout(self):
        u, w = self.u, self.w
        rows = self._rows()
        kh, gap = 58 * u, 8 * u
        y0 = 232 * u
        keys = []
        kw = (w - 40 * u - 9 * gap) / 10.0
        for ri, row in enumerate(rows):
            n = len(row)
            extra_l = (1.5 * kw + gap) if (ri == 3 and self.page == "abc") else 0
            extra_r = (1.5 * kw + gap) if (ri == 3 and self.page == "abc") else 0
            total = n * kw + (n - 1) * gap + extra_l + extra_r
            x = (w - total) / 2 + extra_l
            for ch in row:
                keys.append((ch, pygame.Rect(int(x), int(y0 + ri * (kh + gap)), int(kw), int(kh))))
                x += kw + gap
            if ri == 3 and self.page == "abc":
                keys.append(("SHIFT", pygame.Rect(int((w - total) / 2), int(y0 + ri * (kh + gap)), int(1.5 * kw), int(kh))))
                keys.append(("BKSP", pygame.Rect(int(x), int(y0 + ri * (kh + gap)), int(1.5 * kw), int(kh))))
        yb = y0 + len(rows) * (kh + gap)
        if self.page == "sym":
            keys.append(("BKSP", pygame.Rect(int(w - 40 * u - 2 * kw), int(y0 + 3 * (kh + gap)), int(1.5 * kw), int(kh))))
        keys.append(("PAGE", pygame.Rect(int(20 * u), int(yb), int(2 * kw), int(kh))))
        keys.append(("SPACE", pygame.Rect(int(20 * u + 2 * kw + gap), int(yb), int(w - 40 * u - 4 * kw - 2 * gap - 2 * gap - kw), int(kh))))
        keys.append(("OK", pygame.Rect(int(w - 20 * u - 2 * kw), int(yb), int(2 * kw), int(kh))))
        return keys

    def priority_hit(self, pos):
        return any(inside(pos, r) for _, r in self._layout())

    def draw(self, surf):
        u, w = self.u, self.w
        surf.fill(BG)
        self.topbar(surf, self.prompt or "Type text", accent=BLUE)
        if self.hint:
            self.text(surf, self.hint, w / 2, 92 * u, 18, MUTED, False, center=True)
        field = pygame.Rect(int(30 * u), int(122 * u), int(w - 60 * u - (70 * u if self.password else 0)), int(70 * u))
        pygame.draw.rect(surf, CARD, field, border_radius=int(14 * u))
        pygame.draw.rect(surf, BLUE, field, width=2, border_radius=int(14 * u))
        shown = self.text_val if (not self.password or self.show) else "\u2022" * len(self.text_val)
        t = font(30 * u).render(shown[-34:] + ("|" if int(time.time() * 2) % 2 == 0 else ""), True, TEXT)
        surf.blit(t, (field.left + 18 * u, field.centery - t.get_height() / 2))
        if self.password:
            r = self._eye_rect()
            button(surf, r, MUTED)
            ic_eye(surf, r.centerx, r.centery, 18 * u, MUTED, off=not self.show)
        now = time.time()
        for lab, r in self._layout():
            hot = self.pressed[0] == lab and now - self.pressed[1] < 0.12
            col = BLUE if lab == "OK" else MUTED if len(lab) > 1 else TEXT
            button(surf, r, col, mix(CARD, BLUE, 0.5) if hot else (mix(CARD, GREEN, 0.4) if lab == "OK" else None))
            if lab == "BKSP":
                icon_arrow(surf, r.centerx, r.centery, 16 * u, TEXT, True)
            elif lab == "SHIFT":
                self.text(surf, "ABC" if not self.shift else "abc", r.centerx, r.centery - 11 * u, 20, TEXT, center=True)
            elif lab == "PAGE":
                self.text(surf, "?123" if self.page == "abc" else "abc", r.centerx, r.centery - 11 * u, 20, TEXT, center=True)
            elif lab == "SPACE":
                self.text(surf, "space", r.centerx, r.centery - 10 * u, 18, MUTED, False, center=True)
            elif lab == "OK":
                self.text(surf, "OK", r.centerx, r.centery - 12 * u, 22, TEXT, center=True)
            else:
                self.text(surf, lab, r.centerx, r.centery - 14 * u, 26, TEXT, center=True)

    def _eye_rect(self):
        u = self.u
        return pygame.Rect(int(self.w - 90 * u), int(122 * u), int(60 * u), int(70 * u))

    def on_down(self, pos):
        if self.password and inside(pos, self._eye_rect()):
            self.show = not self.show
            return
        for lab, r in self._layout():
            if not inside(pos, r):
                continue
            self.pressed = (lab, time.time())
            if lab == "BKSP":
                self.text_val = self.text_val[:-1]
            elif lab == "SHIFT":
                self.shift = not self.shift
            elif lab == "PAGE":
                self.page = "sym" if self.page == "abc" else "abc"
            elif lab == "SPACE":
                self._add(" ")
            elif lab == "OK":
                cb, val = self.cb, self.text_val
                self.app.back()
                if cb:
                    cb(val)
            else:
                self._add(lab)
                if self.shift:
                    self.shift = False
            return

    def _add(self, ch):
        if len(self.text_val) < self.maxlen:
            self.text_val += ch

    def context(self):
        return "An on-screen keyboard asking: %s." % self.prompt


# ----------------------------------------------------------------------------- confirm dialog
class ConfirmScreen(Screen):
    name = "confirm"
    mini = False
    has_back = False

    def __init__(self, app):
        super().__init__(app)
        self.msg, self.on_yes, self.yes_label, self.danger = "", None, "Yes", False

    def enter(self, msg="", on_yes=None, yes_label="Yes", danger=False, **kw):
        self.msg, self.on_yes, self.yes_label, self.danger = msg, on_yes, yes_label, danger

    def _btns(self):
        u, w, h = self.u, self.w, self.h
        bw, bh = 200 * u, 70 * u
        return (pygame.Rect(int(w / 2 - bw - 20 * u), int(h * 0.58), int(bw), int(bh)),
                pygame.Rect(int(w / 2 + 20 * u), int(h * 0.58), int(bw), int(bh)))

    def draw(self, surf):
        u, w, h = self.u, self.w, self.h
        surf.fill(BG)
        card = pygame.Rect(int(w * 0.15), int(h * 0.2), int(w * 0.7), int(h * 0.55))
        pygame.draw.rect(surf, CARD, card, border_radius=int(22 * u))
        pygame.draw.rect(surf, RED if self.danger else BLUE, card, width=3, border_radius=int(22 * u))
        words, line, y = self.msg.split(), "", h * 0.28
        for wd in words + [None]:
            test = (line + " " + wd).strip() if wd else line
            if wd is None or font(28 * u).render(test, True, TEXT).get_width() > card.width - 60 * u:
                self.text(surf, line, w / 2, y, 28, TEXT, center=True)
                y += 40 * u
                line = wd or ""
            else:
                line = test
        no, yes = self._btns()
        button(surf, no, MUTED)
        self.text(surf, "Cancel", no.centerx, no.centery - 14 * u, 24, TEXT, center=True)
        button(surf, yes, RED if self.danger else GREEN, mix(CARD, RED if self.danger else GREEN, 0.4))
        self.text(surf, self.yes_label, yes.centerx, yes.centery - 14 * u, 24, TEXT, center=True)

    def on_up(self, pos):
        no, yes = self._btns()
        if inside(pos, no):
            self.app.back()
        elif inside(pos, yes):
            cb = self.on_yes
            self.app.back()
            if cb:
                cb()
