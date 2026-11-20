"""Room-analysis dashboard shown for ANALYSIS_SECONDS."""
import math
import time

import pygame

from .face import font
from .util import clamp, lerp, mix

BG = (8, 12, 22)
CARD = (17, 25, 42)
TRACK = (36, 48, 70)
TEXT = (230, 240, 255)
MUTED = (125, 145, 175)
GREEN, AMBER, ORANGE, RED, BLUE, GREY = (80, 225, 150), (255, 200, 70), (255, 140, 60), (255, 80, 70), (90, 160, 255), (110, 120, 140)


def arc_band(surf, color, c, r_out, r_in, a0, a1, steps=48):
    """Filled ring segment. Angles in degrees, 0 = right, counter-clockwise positive."""
    if abs(a1 - a0) < 0.5:
        return
    outer, inner = [], []
    for i in range(steps + 1):
        a = math.radians(lerp(a0, a1, i / steps))
        outer.append((c[0] + math.cos(a) * r_out, c[1] - math.sin(a) * r_out))
        inner.append((c[0] + math.cos(a) * r_in, c[1] - math.sin(a) * r_in))
    pygame.draw.polygon(surf, color, outer + inner[::-1])


def temp_color(t):
    if t is None:
        return GREY
    return BLUE if t < 18 else GREEN if t < 28 else AMBER if t < 32 else RED


def hum_color(h):
    if h is None:
        return GREY
    return AMBER if h < 30 else GREEN if h < 60 else AMBER if h < 75 else RED


def aq_color(level):
    return {-1: GREY, 0: GREEN, 1: AMBER, 2: ORANGE, 3: RED}.get(level, GREY)


class AnalysisScreen:
    def __init__(self, size, seconds):
        self.w, self.h = size
        self.seconds = seconds
        self.start = time.time()
        self.anim = {}

    def restart(self):
        self.start = time.time()
        self.anim = {}

    def remaining(self):
        return max(0.0, self.seconds - (time.time() - self.start))

    # ------------------------------------------------------------------ draw
    def draw(self, surf, s, manual=False):
        w, h = self.w, self.h
        u = h / 600.0
        el = time.time() - self.start
        ease = 1 - (1 - clamp(el / 0.9, 0, 1)) ** 3
        surf.fill(BG)
        # header
        surf.blit(font(34 * u).render("ROOM ANALYSIS" + ("  -  LIVE" if manual else ""), True, TEXT), ((100 if manual else 36) * u, 22 * u))
        clock = font(30 * u).render(time.strftime("%H:%M"), True, MUTED)
        surf.blit(clock, (w - clock.get_width() - 36 * u, 26 * u))
        pygame.draw.rect(surf, mix(BG, BLUE, 0.6), pygame.Rect(int((100 if manual else 36) * u), int(70 * u), int(120 * u), int(4 * u)), border_radius=2)
        # cards
        margin, gap = 30 * u, 18 * u
        cw = (w - 2 * margin - 3 * gap) / 4
        top, ch = 100 * u, 380 * u
        t, hu, p = s["temperature"], s["humidity"], s["pressure"]
        if t is None:
            tsub = "No sensor"
        else:
            tsub = "Cold" if t < 18 else "Comfortable" if t < 28 else "Warm" if t < 32 else "Hot"
        cards = [
            ("TEMPERATURE", t, "%.1f" % t if t is not None else "--", "\u00b0C", 0, 50, temp_color(t),
             tsub, "thermo"),
            ("HUMIDITY", hu, "%.0f" % hu if hu is not None else "--", "%", 0, 100, hum_color(hu),
             "Dry" if hu is not None and hu < 30 else "Humid" if hu is not None and hu >= 75 else "Normal" if hu is not None else "No sensor", "drop"),
            ("AIR PRESSURE", p, "%.0f" % p if p is not None else "--", "hPa", 900, 1050, BLUE if p is not None else GREY,
             {"sensor": "BMP280", "online": "Online data", "sim": "Simulated"}.get(s["pressure_src"], "Needs sensor / net"), "gauge"),
            ("AIR QUALITY", s["aq_pct"] if s["aq_level"] >= 0 else None, s["aq_label"], "", 0, 100, aq_color(s["aq_level"]),
             "Gas level %d%%" % s["aq_pct"] if s["aq_level"] >= 0 else "Sensor heating", "air"),
        ]
        for i, (title, val, txt, unit, lo, hi, col, sub, icon) in enumerate(cards):
            x = margin + i * (cw + gap)
            card = pygame.Rect(int(x), int(top), int(cw), int(ch))
            pygame.draw.rect(surf, mix(BG, col, 0.10) if val is not None else CARD, card, border_radius=int(22 * u))
            pygame.draw.rect(surf, mix(CARD, col, 0.45), card, width=2, border_radius=int(22 * u))
            surf.blit(font(19 * u).render(title, True, MUTED), (x + 22 * u, top + 18 * u))
            ccx, ccy, r = x + cw / 2, top + 190 * u, cw * 0.40
            f = 0.0 if val is None else clamp((val - lo) / float(hi - lo), 0, 1)
            if title == "AIR QUALITY" and val is not None:
                f = clamp(val / 100.0, 0.04, 1)
            arc_band(surf, TRACK, (ccx, ccy), r, r - 20 * u, 210, -30)
            fa = 210 - 240 * f * ease
            arc_band(surf, col, (ccx, ccy), r, r - 20 * u, 210, fa)
            # needle dot
            na = math.radians(fa)
            pygame.draw.circle(surf, TEXT, (int(ccx + math.cos(na) * (r - 10 * u)), int(ccy - math.sin(na) * (r - 10 * u))), int(8 * u))
            self._icon(surf, icon, ccx, ccy - 6 * u, u, mix(col, TEXT, 0.4))
            big = font((54 if title != "AIR QUALITY" else 34) * u).render(txt, True, TEXT)
            surf.blit(big, (ccx - big.get_width() / 2, top + 258 * u))
            if unit:
                un = font(22 * u).render(unit, True, MUTED)
                surf.blit(un, (ccx - un.get_width() / 2, top + 320 * u))
            sb = font(20 * u).render(sub, True, col)
            surf.blit(sb, (ccx - sb.get_width() / 2, top + ch - 38 * u))
        # comfort summary
        msg = "Room feels: %s" % s["comfort"]
        if s["gas_alert"]:
            msg = "WARNING: gas / smoke detected - ventilate the room!"
        m = font(26 * u).render(msg, True, RED if s["gas_alert"] else TEXT)
        surf.blit(m, (w / 2 - m.get_width() / 2, 498 * u))
        if manual:
            cd = font(18 * u).render("Live readings  \u2022  press Back to return", True, MUTED)
            surf.blit(cd, (w / 2 - cd.get_width() / 2, 556 * u))
            return
        rem = self.remaining()
        bw, bx, by = w - 2 * margin, margin, 548 * u
        pygame.draw.rect(surf, TRACK, pygame.Rect(int(bx), int(by), int(bw), int(10 * u)), border_radius=5)
        fw = int(bw * rem / self.seconds)
        if fw > 0:
            pygame.draw.rect(surf, BLUE, pygame.Rect(int(bx), int(by), fw, int(10 * u)), border_radius=min(5, fw // 2))
        cd = font(18 * u).render("Back to Luna in %ds  \u2022  tap to close" % math.ceil(rem), True, MUTED)
        surf.blit(cd, (w / 2 - cd.get_width() / 2, 566 * u))

    @staticmethod
    def _icon(surf, kind, cx, cy, u, c):
        d = pygame.draw
        if kind == "thermo":
            d.rect(surf, c, pygame.Rect(int(cx - 6 * u), int(cy - 34 * u), int(12 * u), int(50 * u)), border_radius=int(6 * u))
            d.circle(surf, c, (int(cx), int(cy + 20 * u)), int(15 * u))
        elif kind == "drop":
            d.circle(surf, c, (int(cx), int(cy + 8 * u)), int(24 * u))
            d.polygon(surf, c, [(cx - 22 * u, cy), (cx + 22 * u, cy), (cx, cy - 42 * u)])
        elif kind == "gauge":
            d.circle(surf, c, (int(cx), int(cy + 4 * u)), int(30 * u), int(5 * u))
            d.line(surf, c, (cx, cy + 4 * u), (cx + 16 * u, cy - 14 * u), int(5 * u))
        else:
            for i in range(3):
                y = cy - 22 * u + i * 20 * u
                pts = [(cx - 34 * u + k * 8 * u, y + math.sin(k * 0.9 + i) * 5 * u) for k in range(9)]
                d.lines(surf, c, False, pts, int(5 * u))
