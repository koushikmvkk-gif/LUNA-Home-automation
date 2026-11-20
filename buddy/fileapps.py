"""PDF reader (poppler) and the file browser for Luna's documents and USB pen drives."""
import hashlib
import logging
import os
import re
import subprocess
import tempfile
import threading
import time

import pygame

from . import files as F
from .face import font
from .screens import AMBER, BG, BLUE, CARD, GREEN, MUTED, PURPLE, RED, TEXT, TRACK, WHITE, button, icon_arrow, inside, load_image
from .ui import ListView, Screen, icon, ic_zoom
from .util import clamp, mix, state_load, state_save

log = logging.getLogger("fileapps")
RED_PDF = (255, 110, 100)


# ----------------------------------------------------------------------------- PDF backend (poppler-utils)
class PdfDoc:
    def __init__(self, cfg, path):
        self.cfg, self.path = cfg, path
        self.pages, self.title, self.w_pt, self.h_pt = 1, os.path.splitext(os.path.basename(path))[0], 595.0, 842.0
        self.cache_dir = os.path.join(tempfile.gettempdir(), "luna_pdf", hashlib.sha1(path.encode()).hexdigest()[:12])
        os.makedirs(self.cache_dir, exist_ok=True)
        self.ok = False
        self._info()

    def _info(self):
        try:
            out = subprocess.run(["pdfinfo", self.path], capture_output=True, text=True, timeout=15).stdout
            m = re.search(r"Pages:\s+(\d+)", out)
            if m:
                self.pages, self.ok = int(m.group(1)), True
            m = re.search(r"Page size:\s+([\d.]+) x ([\d.]+)", out)
            if m:
                self.w_pt, self.h_pt = float(m.group(1)), float(m.group(2))
            m = re.search(r"Title:\s+(.+)", out)
            if m and m.group(1).strip():
                self.title = m.group(1).strip()
        except Exception as e:
            log.warning("pdfinfo failed: %s", e)

    def render(self, page, dpi):
        """Render one page to a PNG (cached). Returns the file path or None."""
        dpi = int(dpi)
        out = os.path.join(self.cache_dir, "p%d_%d" % (page, dpi))
        if os.path.exists(out + ".png"):
            return out + ".png"
        try:
            subprocess.run(["pdftoppm", "-r", str(dpi), "-f", str(page), "-l", str(page), "-png", "-singlefile", self.path, out],
                           capture_output=True, timeout=90)
        except Exception as e:
            log.warning("pdftoppm failed: %s", e)
        return out + ".png" if os.path.exists(out + ".png") else None

    def text(self, page):
        try:
            out = subprocess.run(["pdftotext", "-f", str(page), "-l", str(page), "-nopgbrk", self.path, "-"], capture_output=True, text=True, timeout=20).stdout
        except Exception:
            return ""
        return out


def speech_chunks(text, limit=320):
    text = re.sub(r"-\n(?=[a-z])", "", text)                 # re-join hyphenated words
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    sentences = []
    for p in paras:
        sentences += [s for s in re.split(r"(?<=[.!?:;])\s+", p) if s.strip()]
    chunks, cur = [], ""
    for s in sentences:
        if len(cur) + len(s) + 1 > limit and cur:
            chunks.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        chunks.append(cur)
    return chunks


ZOOMS = [1.0, 1.5, 2.2]


class PdfScreen(Screen):
    name, title, accent = "pdf", "PDF reader", RED_PDF
    mini_pos = "tr"

    def enter(self, path="", page=None, **kw):
        self.path = path
        self.doc = PdfDoc(self.app.cfg, path)
        self.title = self.doc.title[:40]
        saved = state_load(self.app.cfg).get("pdf_pos", {}).get(path, 1)
        self.page = int(clamp(page or saved, 1, self.doc.pages))
        self.zi = 0
        self.img, self.img_key, self.loading = None, None, False
        self.off = [0.0, 0.0]
        self.drag, self.dstart = None, None
        self.reading, self.chunks, self.continuous = False, [], True
        self.msg = "" if self.doc.ok else "Could not read this PDF (is poppler-utils installed?)"
        self._request()

    def leave(self):
        self.stop_reading()

    # ------------------------------------------------------------ layout / render
    def _area(self):
        u = self.u
        return pygame.Rect(0, int(78 * u), self.w, int(self.h - 78 * u - 84 * u))

    def _fit_dpi(self):
        # fit the page WIDTH to the screen (readable text); drag up / down to scroll the page
        a = self._area()
        return min(self.app.cfg.PDF_BASE_DPI_MAX, max(40, a.width / (self.doc.w_pt / 72.0)))

    def _request(self):
        key = (self.page, self.zi)
        if key == self.img_key or self.loading:
            return
        self.loading = True
        page, zi = self.page, self.zi
        dpi = min(260, self._fit_dpi() * ZOOMS[zi])

        def work():
            p = self.doc.render(page, dpi)
            img = load_image(p) if p else None
            self.app.events.put(("call", (lambda r: self._loaded(page, zi, r), img)))
            if zi == 0 and page < self.doc.pages:
                self.doc.render(page + 1, self._fit_dpi())                   # prefetch the next page
        threading.Thread(target=work, daemon=True).start()

    def _loaded(self, page, zi, img):
        self.loading = False
        if img is not None:
            self.img, self.img_key = img, (page, zi)
            self.off = [0.0, 0.0]
        if (self.page, self.zi) != (page, zi):
            self._request()

    def goto(self, page):
        page = int(clamp(page, 1, self.doc.pages))
        if page != self.page:
            self.page = page
            self.zi = 0
            st = state_load(self.app.cfg).get("pdf_pos", {})
            st[self.path] = page
            state_save(self.app.cfg, pdf_pos=st)
            self._request()
        return page

    def zoom(self, delta):
        zi = int(clamp(self.zi + delta, 0, len(ZOOMS) - 1))
        if zi != self.zi:
            self.zi = zi
            self._request()

    # ------------------------------------------------------------ reading aloud
    def start_reading(self):
        self.reading = True
        self.chunks = speech_chunks(self.doc.text(self.page), self.app.cfg.PDF_READ_CHARS)
        if not self.chunks:
            self.app.speaker.say("This page has no text I can read. It may be a scanned picture.")
            self.chunks = []

    def stop_reading(self):
        if self.reading:
            self.reading = False
            self.chunks = []
            self.app.speaker.stop_now()

    def tick(self, dt):
        if not self.reading:
            return
        sp = self.app.speaker
        if sp.busy():
            return
        if self.chunks:
            sp.say(self.chunks.pop(0))
        elif self.continuous and self.page < self.doc.pages:
            self.goto(self.page + 1)
            self.chunks = speech_chunks(self.doc.text(self.page), self.app.cfg.PDF_READ_CHARS)
        else:
            self.reading = False
            if self.page >= self.doc.pages:
                sp.say("That is the end of the document.")

    # ------------------------------------------------------------ draw
    def _bar_btns(self):
        u = self.u
        y = self.h - 76 * u
        names = ["prev", "page", "next", "zout", "zin", "read"]
        sizes = [64, 150, 64, 64, 64, 150]
        x = 30 * u
        out = {}
        for n, s in zip(names, sizes):
            out[n] = pygame.Rect(int(x), int(y), int(s * u), int(64 * u))
            x += s * u + 14 * u
        return out

    def draw(self, surf):
        u, w, h = self.u, self.w, self.h
        surf.fill((38, 42, 52))
        a = self._area()
        if self.img is not None:
            iw, ih = self.img.get_size()
            fit = self.zi == 0
            x = a.left + (a.width - iw) / 2 if iw <= a.width else a.left + self.off[0]
            y = a.top + (a.height - ih) / 2 if ih <= a.height else a.top + self.off[1]
            if iw > a.width:
                self.off[0] = clamp(self.off[0], a.width - iw, 0)
                x = a.left + self.off[0]
            if ih > a.height:
                self.off[1] = clamp(self.off[1], a.height - ih, 0)
                y = a.top + self.off[1]
            surf.blit(self.img, (int(x), int(y)))
        else:
            self.text(surf, self.msg or "Loading page...", w / 2, h / 2 - 20 * u, 26, MUTED, center=True)
        if self.loading and self.img is not None:
            self.text(surf, "Loading...", w - 120 * u, 90 * u, 16, AMBER)
        self.topbar(surf, self.title)
        pygame.draw.rect(surf, mix(BG, self.accent, 0.12), pygame.Rect(0, int(h - 84 * u), w, int(84 * u)))
        pygame.draw.line(surf, self.accent, (0, int(h - 84 * u)), (w, int(h - 84 * u)), 2)
        for n, r in self._bar_btns().items():
            on = n == "read" and self.reading
            button(surf, r, GREEN if on else (self.accent if n == "page" else MUTED), mix(CARD, GREEN, 0.4) if on else None)
            cx, cy, s = r.centerx, r.centery, 18 * u
            if n == "prev":
                icon_arrow(surf, cx, cy, s, TEXT, True)
            elif n == "next":
                icon_arrow(surf, cx, cy, s, TEXT, False)
            elif n == "page":
                self.text(surf, "%d / %d" % (self.page, self.doc.pages), cx, cy - 13 * u, 22, TEXT, center=True)
            elif n == "zin":
                ic_zoom(surf, cx, cy, s * 0.9, TEXT, True)
            elif n == "zout":
                ic_zoom(surf, cx, cy, s * 0.9, TEXT, False)
            else:
                icon(surf, "speaker", r.left + 36 * u, cy, 16 * u, GREEN if on else TEXT)
                self.text(surf, "Stop" if on else "Read aloud", r.left + 64 * u, cy - 11 * u, 18, TEXT)

    # ------------------------------------------------------------ input
    def on_down(self, pos):
        self.drag, self.dstart, self.moved = pos, pos, 0.0

    def on_move(self, pos):
        if self.drag is None:
            return
        dx, dy = pos[0] - self.drag[0], pos[1] - self.drag[1]
        self.moved += abs(dx) + abs(dy)
        self.drag = pos
        if self.img is not None and (self.img.get_width() > self.w or self.img.get_height() > self._area().height):
            self.off[0] += dx
            self.off[1] += dy

    def on_up(self, pos):
        if self.drag is None:
            return
        start, self.drag = self.dstart, None
        u = self.u
        for n, r in self._bar_btns().items():
            if inside(pos, r) and inside(start, r):
                self._press(n)
                return
        if self.zi == 0 and abs(pos[0] - start[0]) > 120 * u and abs(pos[1] - start[1]) < 90 * u:
            self.goto(self.page + (1 if pos[0] < start[0] else -1))
        elif self.moved < 14 * u and self.img is not None:                      # tap near the top / bottom edge of the page area = scroll
            a = self._area()
            if self.img.get_height() > a.height and inside(pos, a):
                self.off[1] += a.height * 0.8 * (1 if pos[1] < a.centery else -1)

    def _press(self, n):
        if n == "prev":
            self.goto(self.page - 1)
        elif n == "next":
            self.goto(self.page + 1)
        elif n == "zin":
            self.zoom(1)
        elif n == "zout":
            self.zoom(-1)
        elif n == "read":
            self.stop_reading() if self.reading else self.start_reading()
        elif n == "page":
            def got(t):
                if t and t.strip().isdigit():
                    self.goto(int(t))
            self.app.ask_text("Go to page (1 - %d)" % self.doc.pages, "", got, hint="type the page number")

    def context(self):
        return "The PDF reader showing '%s', page %d of %d%s." % (self.title, self.page, self.doc.pages, ", reading aloud" if self.reading else "")

    def comment(self):
        return "This document has %d pages. Say, Luna, read this page, and I will read it to you." % self.doc.pages


# ----------------------------------------------------------------------------- file browser
class FilesScreen(Screen):
    name, title, accent = "files", "Files", (110, 200, 255)
    cur = None
    root = None
    mode = "docs"

    def enter(self, start="docs", path=None, **kw):
        self.mode = start
        self.root = self.app.cfg.PDF_DIR if start == "docs" else None
        os.makedirs(self.app.cfg.PDF_DIR, exist_ok=True)
        self.cur = self.root
        self.lv = ListView(self.u)
        self.entries, self.drives = [], []
        self.title = "Documents" if start == "docs" else "USB drive"
        if start == "usb":
            drives = F.usb_drives(self.app.cfg)
            if len(drives) == 1:
                self.root = self.cur = drives[0]["path"]
        elif path:
            self.cur = self.root = path
        self.refresh()

    def resume(self):
        self.refresh()

    def drive_gone(self, path):
        if self.cur and self.cur.startswith(path):
            self.root = self.cur = None
            self.refresh()

    def refresh(self):
        a = self.app
        rows = []
        if self.cur is None:
            self.drives = F.usb_drives(a.cfg)
            for d in self.drives:
                rows.append(dict(label=d["label"], sub="%s free of %s" % (F.human(d["free"]), F.human(d["total"])), icon="usb", tag=("drive", d["path"]), col=self.accent))
            if not rows:
                rows.append(dict(label="No USB drive found", sub="Plug in a pen drive - it appears here by itself", icon="usb", tag=("none", None), col=MUTED))
            self.title = "USB drive"
        else:
            self.entries = F.list_dir(self.cur)
            for i, (n, fp, k, size) in enumerate(self.entries):
                col = {"folder": AMBER, "pdf": RED_PDF, "image": BLUE, "audio": (255, 120, 170), "video": (255, 160, 70), "text": (150, 215, 255)}.get(k, MUTED)
                sub = "%d item%s" % (size, "" if size == 1 else "s") if k == "folder" else F.human(size)
                rows.append(dict(label=n, sub=sub, icon={"folder": "folder", "pdf": "pdf", "image": "gallery", "audio": "music", "video": "film", "text": "file"}.get(k, "file"), tag=("entry", i), col=col))
            if not rows:
                rows.append(dict(label="This folder is empty", sub="Copy PDFs into data/pdfs/ or open a USB drive" if self.mode == "docs" else "", icon="folder", tag=("none", None), col=MUTED))
            base = self.root or self.cur
            rel = os.path.relpath(self.cur, os.path.dirname(base)) if self.cur else ""
            self.title = ("Documents" if self.mode == "docs" and self.cur == self.root else rel)[:40]
        self.lv.set_rows(rows)

    def on_back(self):
        if self.cur is None or (self.mode == "docs" and self.cur == self.root):
            self.app.back()
        elif self.mode == "usb" and self.cur == self.root:
            if len(F.usb_drives(self.app.cfg)) <= 1:
                self.app.back()
            else:
                self.cur = self.root = None
                self.refresh()
        else:
            self.cur = os.path.dirname(self.cur)
            self.refresh()

    def _btns(self):
        u = self.u
        if self.mode == "usb" and self.cur is not None and self.cur == self.root:
            return {"backup": pygame.Rect(int(self.w - 350 * u), int(14 * u), int(170 * u), int(52 * u)),
                    "eject": pygame.Rect(int(self.w - 170 * u), int(14 * u), int(150 * u), int(52 * u))}
        return {}

    def draw(self, surf):
        u = self.u
        surf.fill(BG)
        self.topbar(surf, self.title)
        for n, r in self._btns().items():
            button(surf, r, GREEN if n == "backup" else AMBER)
            self.text(surf, "Backup to USB" if n == "backup" else "Eject", r.centerx, r.centery - 11 * u, 18, TEXT, center=True)
        self.lv.draw(surf, pygame.Rect(int(40 * u), int(92 * u), int(self.w - 80 * u), int(self.h - 108 * u)), self.accent)

    def on_down(self, pos):
        self.lv.down(pos)

    def on_move(self, pos):
        self.lv.move(pos)

    def on_up(self, pos):
        for n, r in self._btns().items():
            if inside(pos, r):
                self.lv.down_pos = None
                (self.app.usb_backup if n == "backup" else self.app.usb_eject)(self.cur)
                return
        tag = self.lv.up(pos)
        if not tag:
            return
        kind, val = tag
        if kind == "drive":
            self.root = self.cur = val
            self.refresh()
        elif kind == "entry":
            name, fp, k, size = self.entries[val]
            if self.lv.last_hold > 0.7 and k != "folder":
                self._options(fp, k)
            else:
                self._open(val)

    def _options(self, fp, k):
        a = self.app
        opts = [("Open", os.path.basename(fp), lambda: self._open(next(i for i, e in enumerate(self.entries) if e[1] == fp)), GREEN)]
        if self.mode == "usb":
            opts.append(("Copy to Luna" if k != "image" else "Copy to Gallery", "Keep a copy on the robot", lambda: a.run_bg(lambda: F.copy_to_luna(a.cfg, fp), lambda m: a.toast(m or "Copy failed", 3)), BLUE))
        a.choose(os.path.basename(fp)[:40], opts, self.accent)

    def _open(self, i):
        a = self.app
        name, fp, k, size = self.entries[i]
        if k == "folder":
            self.cur = fp
            self.refresh()
        elif k == "pdf":
            a.open("pdf", path=fp)
        elif k == "text":
            a.open("textview", path=fp)
        elif k == "image":
            imgs = [e[1] for e in self.entries if e[2] == "image"]
            a.open("gallery", mode="list", files=imgs, index=imgs.index(fp))
        elif k == "audio":
            from .music import Track, norm
            tracks = [Track(norm(e[0]).title() or e[0], e[1], "USB") for e in self.entries if e[2] == "audio"]
            idx = next(j for j, t in enumerate(tracks) if t.path == fp)
            a.play_tracks(tracks, idx)
            a.toast("Playing %s" % tracks[idx].title)
        elif k == "video":
            a.play_video(fp)
        else:
            a.toast("Luna cannot open this kind of file yet")

    def context(self):
        return "The file browser showing %s with %d entries." % (self.title, len(self.lv.rows))

    def comment(self):
        return "Tap a PDF to read it, or hold a file to copy it to my memory." if self.mode == "usb" else "These are your documents. Tap a PDF and I can read it out loud for you."


from .util import harden as _harden          # noqa: E402
_harden(FilesScreen, ("enter", "refresh", "on_down", "on_move", "on_up", "_open", "_options", "on_back"))
_harden(PdfScreen, ("enter", "on_down", "on_move", "on_up", "tick"))
