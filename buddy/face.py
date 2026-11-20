"""The animated robot face (pure pygame drawing, no image files needed)."""
import math
import random

import pygame

from .util import clamp, lerp, mix

BG = (8, 12, 22)
WHITE = (255, 255, 255)
CYAN = (80, 220, 255)

#            open  tilt cheek curve mopen mw    colour            style    extras
EXPR = {
    "neutral":   dict(open=1.00, tilt=0.0,  cheek=0.0,  curve=0.35, mopen=0.0, mw=0.30, color=CYAN, style="round", extras=()),
    "happy":     dict(open=0.95, tilt=0.0,  cheek=0.45, curve=0.90, mopen=0.35, mw=0.34, color=(100, 240, 210), style="round", extras=("blush",)),
    "joy":       dict(open=0.90, tilt=0.0,  cheek=0.0,  curve=0.90, mopen=0.80, mw=0.36, color=(255, 225, 110), style="arc", extras=("blush",)),
    "love":      dict(open=1.00, tilt=0.0,  cheek=0.0,  curve=0.90, mopen=0.30, mw=0.30, color=(255, 90, 150), style="heart", extras=("blush", "hearts")),
    "sad":       dict(open=0.85, tilt=-0.9, cheek=0.0,  curve=-0.80, mopen=0.0, mw=0.22, color=(100, 150, 255), style="round", extras=("tear",)),
    "angry":     dict(open=0.80, tilt=0.9,  cheek=0.0,  curve=-0.55, mopen=0.0, mw=0.30, color=(255, 80, 60), style="round", extras=()),
    "surprised": dict(open=1.25, tilt=0.0,  cheek=0.0,  curve=0.0,  mopen=1.0, mw=0.14, color=(190, 245, 255), style="round", extras=()),
    "sleepy":    dict(open=0.30, tilt=-0.35, cheek=0.0, curve=0.10, mopen=0.0, mw=0.20, color=(70, 130, 170), style="round", extras=()),
    "sleep":     dict(open=0.50, tilt=0.0,  cheek=0.0,  curve=0.20, mopen=0.0, mw=0.16, color=(60, 105, 150), style="closed", extras=("zzz",)),
    "thinking":  dict(open=0.90, tilt=0.30, cheek=0.0,  curve=0.0,  mopen=0.0, mw=0.16, color=(150, 170, 255), style="round", extras=("dots",), gaze=(-0.7, -0.7)),
    "confused":  dict(open=0.95, tilt=0.15, cheek=0.0,  curve=-0.20, mopen=0.0, mw=0.20, color=(200, 190, 255), style="round", extras=("question",), gaze=(0.5, -0.3)),
    "hot":       dict(open=0.70, tilt=-0.20, cheek=0.0, curve=-0.20, mopen=0.55, mw=0.24, color=(255, 150, 70), style="round", extras=("sweat",)),
    "cold":      dict(open=0.80, tilt=-0.30, cheek=0.0, curve=-0.35, mopen=0.20, mw=0.26, color=(150, 225, 255), style="round", extras=("shiver",)),
    "alert":     dict(open=1.20, tilt=0.50, cheek=0.0,  curve=-0.30, mopen=0.50, mw=0.28, color=(255, 70, 60), style="round", extras=("alert",)),
    "wink":      dict(open=0.95, tilt=0.0,  cheek=0.35, curve=0.90, mopen=0.25, mw=0.32, color=(100, 240, 210), style="wink", extras=("blush",)),
    "police":    dict(open=0.80, tilt=0.55, cheek=0.0,  curve=0.0,  mopen=0.0, mw=0.22, color=(90, 150, 255), style="round", extras=("police",)),
    "listening": dict(open=1.10, tilt=0.0,  cheek=0.0,  curve=0.25, mopen=0.0, mw=0.22, color=(120, 235, 255), style="round", extras=("bars",)),
}

_fonts = {}


def font(size, bold=True):
    key = (int(size), bold)
    if key not in _fonts:
        _fonts[key] = pygame.font.SysFont("dejavusans,freesans,arial", int(size), bold=bold)
    return _fonts[key]


def heart_points(cx, cy, size, n=36):
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((cx + x * size / 16.0, cy - y * size / 16.0))
    return pts


class Face:
    def __init__(self, size):
        self.w, self.h = size
        self.s = self.h / 600.0                    # scale (mini face is smaller)
        e = EXPR["neutral"]
        self.cur = {k: e[k] for k in ("open", "tilt", "cheek", "curve", "mopen", "mw")}
        self.color = e["color"]
        self.style = "round"
        self.pending_style = None
        self.name = "neutral"
        self.extras = ()
        self.t = 0.0
        self.blink_t = -1.0
        self.next_blink = 2.0
        self.gaze = [0.0, 0.0]
        self.gaze_target = [0.0, 0.0]
        self.next_gaze = 1.5
        self.speaking = False
        self.bg = BG
        self.look_t = 0.0

    def look_at(self, nx, ny, seconds=1.6):
        """Eyes follow a touch point. nx, ny in -1..1 (screen centre = 0)."""
        self.gaze_target = [max(-1, min(1, nx)) * 1.2, max(-1, min(1, ny)) * 0.9]
        self.look_t = seconds

    def set_emotion(self, name):
        if name not in EXPR:
            name = "neutral"
        if name != self.name:
            self.name = name
            if EXPR[name]["style"] != self.style:
                self.pending_style = EXPR[name]["style"]
            self.extras = EXPR[name]["extras"]
            if name in ("surprised", "alert"):
                self.blink_t = -1.0

    # --------------------------------------------------------------- update
    def update(self, dt):
        self.t += dt
        e = EXPR[self.name]
        k = 1 - math.exp(-dt * 9)
        for key in self.cur:
            if key == "open" and self.pending_style:
                continue                          # eyes are closing for a style change
            self.cur[key] = lerp(self.cur[key], e[key], k)
        self.color = tuple(int(lerp(a, b, k)) for a, b in zip(self.color, e["color"]))
        # style change goes through a quick blink
        if self.pending_style:
            self.cur["open"] = max(0.0, self.cur["open"] * 0.6 - 0.02)
            if self.cur["open"] < 0.08:
                self.style, self.pending_style = self.pending_style, None
        # blinking
        self.next_blink -= dt
        if self.next_blink <= 0 and self.blink_t < 0:
            self.blink_t = 0.0
            self.next_blink = random.uniform(2.5, 6.0)
        if self.blink_t >= 0:
            self.blink_t += dt
            if self.blink_t > 0.18:
                self.blink_t = -1.0
        # gaze
        self.next_gaze -= dt
        g = e.get("gaze")
        if self.look_t > 0:
            self.look_t -= dt                      # following a finger: keep the target
        elif g:
            self.gaze_target = list(g)
        elif self.next_gaze <= 0 and self.look_t <= 0:
            self.next_gaze = random.uniform(1.5, 4.0)
            self.gaze_target = [random.uniform(-0.8, 0.8), random.uniform(-0.4, 0.4)] if random.random() < 0.7 else [0, 0]
        if self.name == "listening" and self.look_t <= 0:
            self.gaze_target = [0, 0]
        for i in (0, 1):
            self.gaze[i] = lerp(self.gaze[i], self.gaze_target[i], 1 - math.exp(-dt * 6))
        # background flash for alerts
        if self.name == "alert":
            self.bg = mix(BG, (80, 0, 0), 0.5 + 0.5 * math.sin(self.t * 8))
        else:
            self.bg = mix(self.bg, BG, 0.2)

    # ----------------------------------------------------------------- draw
    def draw(self, surf):
        w, h, t = self.w, self.h, self.t
        bg = self.bg
        surf.fill(bg)
        shake = random.randint(-3, 3) * self.s if "shiver" in self.extras else 0
        bob = math.sin(t * 1.6) * h * 0.006
        cx = w / 2 + shake
        eye_y = h * 0.40 + bob
        eye_dx = w * 0.205
        ew = w * 0.17
        full_eh = h * 0.36
        openf = self.cur["open"]
        if self.blink_t >= 0:
            openf *= abs(self.blink_t - 0.09) / 0.09 * 0.92 + 0.08
        gx, gy = self.gaze
        col = self.color
        styles = (self.style, self.style)
        if self.style == "wink":
            styles = ("round", "arc")
        for side, ex in ((-1, cx - eye_dx), (1, cx + eye_dx)):
            self._eye(surf, ex + gx * ew * 0.16, eye_y + gy * full_eh * 0.10, side, ew,
                      full_eh * openf, openf, col, bg, styles[0 if side < 0 else 1], gx, gy)
        self._extras(surf, cx, eye_y, eye_dx, ew, full_eh)
        self._mouth(surf, cx, h * 0.76 + bob, col)

    def _eye(self, surf, x, y, side, ew, eh, openf, col, bg, style, gx, gy):
        d = pygame.draw
        if style == "arc":                       # happy ^ ^
            self._arc_eye(surf, x, y, ew, eh, col, up=True)
            return
        if style == "closed":
            self._arc_eye(surf, x, y, ew, eh, col, up=False)
            return
        if style == "heart":
            size = ew * 0.62 * (1 + 0.07 * math.sin(self.t * 7)) * clamp(openf + 0.1, 0.2, 1.2)
            glow = mix(bg, col, 0.25)
            d.polygon(surf, glow, heart_points(x, y, size * 1.18))
            d.polygon(surf, col, heart_points(x, y, size))
            return
        eh = max(6, eh)
        r = int(min(ew, eh) * 0.42)
        rect = pygame.Rect(int(x - ew / 2), int(y - eh / 2), int(ew), int(eh))
        sc = self.s
        for i, a in ((3, 0.07), (2, 0.12), (1, 0.20)):          # soft glow
            gr = rect.inflate(int(i * 12 * sc), int(i * 12 * sc))
            d.rect(surf, mix(bg, col, a), gr, border_radius=int(r + i * 6 * sc))
        d.rect(surf, col, rect, border_radius=r)
        # shiny highlight
        hl = mix(col, WHITE, 0.75)
        d.circle(surf, hl, (int(x - ew * 0.18 + gx * 4), int(y - eh * 0.22 + gy * 3)), max(3, int(ew * 0.075)))
        pad = max(4, int(14 * self.s))
        x0, x1 = rect.left - pad, rect.right + pad
        tilt = self.cur["tilt"]
        inner = max(tilt, 0) * eh * 0.75
        outer = max(-tilt, 0) * eh * 0.75
        lh, rh = (outer, inner) if side < 0 else (inner, outer)
        if inner > 1 or outer > 1:
            d.polygon(surf, bg, [(x0, rect.top - pad), (x1, rect.top - pad),
                                 (x1, rect.top + rh), (x0, rect.top + lh)])
        cheek = self.cur["cheek"]
        if cheek > 0.02:
            rr = ew * 0.78
            d.circle(surf, bg, (int(x), int(rect.bottom + rr - cheek * eh * 0.60)), int(rr))

    def _arc_eye(self, surf, x, y, ew, eh, col, up):
        n = 20
        thick = max(3, int(ew * 0.13))
        for i in range(n + 1):
            a = math.pi * i / n
            px = x + math.cos(a) * ew * 0.42
            py = (y + eh * 0.12 - math.sin(a) * eh * 0.25) if up else (y - eh * 0.05 + math.sin(a) * eh * 0.14)
            pygame.draw.circle(surf, col, (int(px), int(py)), thick // 2)

    # ---------------------------------------------------------------- mouth
    def _mouth(self, surf, cx, my, col):
        w, h = self.w, self.h
        mw = w * self.cur["mw"]
        mh = h * 0.085
        curve, opn = self.cur["curve"], self.cur["mopen"]
        if self.speaking:
            opn = 0.15 + 0.65 * abs(math.sin(self.t * 9.0)) * (0.65 + 0.35 * math.sin(self.t * 3.3))
            curve = max(curve, 0.25)
        lc = mix(col, WHITE, 0.55)
        n = 28
        top, bot = [], []
        for i in range(n + 1):
            u = -1 + 2.0 * i / n
            base = my + curve * mh * (1 - u * u)
            half = opn * mh * 0.55 * (max(0.0, 1 - u * u) ** 0.5)
            x = cx + u * mw / 2
            top.append((x, base - half))
            bot.append((x, base + half))
        if opn > 0.08:
            pygame.draw.polygon(surf, (70, 18, 40), top + bot[::-1])
            pygame.draw.lines(surf, lc, True, top + bot[::-1], max(1, int(4 * self.s)))
        else:
            pygame.draw.lines(surf, lc, False, top, max(2, int(6 * self.s)))
            for p in (top[0], top[-1]):
                pygame.draw.circle(surf, lc, (int(p[0]), int(p[1])), max(1, int(3 * self.s)))

    # --------------------------------------------------------------- extras
    def _extras(self, surf, cx, ey, edx, ew, eh):
        w, h, t, d = self.w, self.h, self.t, pygame.draw
        sc = self.s
        ex = self.extras
        if "blush" in ex:
            c = mix(self.bg, (255, 110, 140), 0.40)
            for s in (-1, 1):
                d.ellipse(surf, c, pygame.Rect(int(cx + s * edx * 1.28 - ew * 0.28), int(ey + eh * 0.52), int(ew * 0.56), int(ew * 0.26)))
        if "hearts" in ex:
            for i in range(4):
                ph = (t * 0.45 + i / 4.0) % 1.0
                x = cx + (i - 1.5) * w * 0.15 + math.sin(ph * 7 + i) * 12 * sc
                y = h * 0.30 - ph * h * 0.28
                d.polygon(surf, mix((255, 110, 160), self.bg, ph ** 1.5), heart_points(x, y, (10 + 8 * (1 - ph)) * sc))
        if "tear" in ex:
            ph = (t * 0.6) % 1.0
            self._drop(surf, cx - edx - ew * 0.2, ey + eh * 0.3 + ph * eh * 0.7, 11 * sc, mix((110, 170, 255), self.bg, ph ** 2))
        if "sweat" in ex:
            ph = (t * 0.5) % 1.0
            self._drop(surf, cx + edx + ew * 0.62, ey - eh * 0.35 + ph * eh * 0.9, 13 * sc, mix((140, 210, 255), self.bg, ph ** 3))
        if "zzz" in ex:
            for i in range(3):
                ph = (t * 0.35 + i / 3.0) % 1.0
                f = font((28 + i * 14 + ph * 10) * sc)
                img = f.render("Z", True, mix((130, 170, 230), self.bg, ph ** 2))
                surf.blit(img, (cx + edx + ew * 0.9 + ph * 60 * sc, h * 0.28 - ph * h * 0.20))
        if "question" in ex:
            img = font(70 * sc).render("?", True, (210, 200, 255))
            surf.blit(img, (cx + edx + ew * 0.55, h * 0.06 + math.sin(t * 3) * 6 * sc))
        if "dots" in ex:
            for i in range(3):
                on = int(t * 2.5) % 3 == i
                d.circle(surf, (190, 200, 255) if on else (80, 90, 140),
                         (int(cx + edx + ew * 0.7 + i * 26 * sc), int(h * 0.12 - (8 if on else 0) * sc)), max(2, int(9 * sc)))
        if "alert" in ex:
            on = int(t * 4) % 2 == 0
            c = (255, 230, 80) if on else (255, 120, 40)
            tx, ty, s = cx, h * 0.085, h * 0.075
            d.polygon(surf, c, [(tx, ty - s), (tx + s * 1.15, ty + s), (tx - s * 1.15, ty + s)])
            img = font(s * 1.6).render("!", True, (60, 10, 10))
            surf.blit(img, (tx - img.get_width() / 2, ty - s * 0.55))
        if "bars" in ex:
            for i in range(7):
                bh = (10 + 26 * abs(math.sin(t * 6 + i * 0.9))) * sc
                d.rect(surf, (90, 210, 255), pygame.Rect(int(cx - 70 * sc + i * 22 * sc), int(h * 0.93 - bh), max(2, int(12 * sc)), int(bh)), border_radius=max(1, int(5 * sc)))
        if "police" in ex:
            on = int(t * 3) % 2 == 0
            hh = max(4, int(14 * sc))
            d.rect(surf, (255, 50, 50) if on else (70, 20, 20), pygame.Rect(0, 0, int(w / 2), hh))
            d.rect(surf, (60, 20, 70) if on else (50, 110, 255), pygame.Rect(int(w / 2), 0, int(w / 2), hh))
            tx = font(26 * sc).render("SECURITY MODE", True, (140, 180, 255))
            surf.blit(tx, (w / 2 - tx.get_width() / 2, h * 0.9))
        if "shiver" in ex:
            d.circle(surf, (200, 240, 255), (int(w * 0.10), int(h * 0.15)), 5)
            d.circle(surf, (200, 240, 255), (int(w * 0.90), int(h * 0.22)), 4)

    @staticmethod
    def _drop(surf, x, y, r, col):
        pygame.draw.circle(surf, col, (int(x), int(y)), int(r))
        pygame.draw.polygon(surf, col, [(x - r * 0.92, y - r * 0.35), (x + r * 0.92, y - r * 0.35), (x, y - r * 2.1)])
