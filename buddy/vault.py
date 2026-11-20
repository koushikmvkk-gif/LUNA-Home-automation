"""Secure hidden vault: VaultManager (logic) + VaultScreen (on-screen PIN / password modal).

Why this file exists
--------------------
Bug: tapping the padlock in the gallery called ``App.request_hidden(replace=False)`` but the method took no
argument -> TypeError -> the exception escaped the main loop -> Luna closed and you landed on Raspberry Pi OS.

Fixes
-----
* ``App.request_hidden`` now accepts ``replace`` (and every gallery / file handler is wrapped by ``guarded``).
* The main loop catches every per-frame exception, logs it to logs/buddy.log and keeps running.
* ``VaultManager`` is the ONLY door to data/hidden/: it hands out the file list only while a PBKDF2-verified
  session is open. Failed tries are counted on disk, so a reboot does not reset the lockout.
* Cancel / wrong PIN / lockout always end with ``on_done("cancel" | "failed" | "locked")`` and the app returns to
  the normal gallery - never to the OS.

The hash file is data/hidden_pin.json, the same file the old PinStore used, so your existing PIN keeps working.
"""
import json
import logging
import math
import os
import stat
import time

import pygame

from .face import font
from .screens import BG, BLUE, CARD, MUTED, PURPLE, RED, TEXT, TRACK, button, icon_arrow, icon_lock, icon_x, inside
from .ui import Screen
from .util import guarded, mix

log = logging.getLogger("vault")

PIN_LEN = 4


class VaultManager:
    """Verifies the secret (4-digit PIN or an alphanumeric password) and guards access to data/hidden/."""

    def __init__(self, cfg, pins):
        self.cfg, self.pins = cfg, pins            # pins = gallery.PinStore (salted PBKDF2-SHA256, 150 000 rounds)
        self._until = 0.0                          # session expiry (monotonic-ish wall clock)
        self._state = self._load()
        self.mount()

    # ------------------------------------------------------------ persistence of lockout state
    def _load(self):
        try:
            with open(self.cfg.VAULT_STATE_FILE) as f:
                d = json.load(f)
            return dict(fails=int(d.get("fails", 0)), locked_until=float(d.get("locked_until", 0)), rounds=int(d.get("rounds", 0)))
        except Exception:
            return dict(fails=0, locked_until=0.0, rounds=0)

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.cfg.VAULT_STATE_FILE), exist_ok=True)
            with open(self.cfg.VAULT_STATE_FILE, "w") as f:
                json.dump(self._state, f)
            os.chmod(self.cfg.VAULT_STATE_FILE, 0o600)
        except Exception as e:
            log.warning("cannot save vault state: %s", e)

    # ------------------------------------------------------------ "mounting" the hidden folder
    def mount(self):
        """Make sure data/hidden/ exists and is private to this user (chmod 700)."""
        try:
            os.makedirs(self.cfg.HIDDEN_DIR, exist_ok=True)
            os.chmod(self.cfg.HIDDEN_DIR, stat.S_IRWXU)
        except Exception as e:
            log.warning("vault mount: %s", e)

    # ------------------------------------------------------------ credentials
    def is_set(self):
        return self.pins.is_set()

    def set_secret(self, secret):
        if not secret or (len(secret) < PIN_LEN):
            return False
        self.pins.set(secret)
        self._state.update(fails=0, locked_until=0.0, rounds=0)
        self._save()
        return True

    def seconds_locked(self):
        return max(0.0, self._state["locked_until"] - time.time())

    def verify(self, secret):
        """-> 'ok' | 'bad' | 'locked'. Three wrong tries lock for 30 s, doubling each round (kept on disk)."""
        if self.seconds_locked() > 0:
            return "locked"
        if secret and self.pins.verify(secret):
            self._state.update(fails=0, locked_until=0.0, rounds=0)
            self._save()
            self.unlock()
            return "ok"
        self._state["fails"] += 1
        if self._state["fails"] >= self.cfg.VAULT_MAX_TRIES:
            self._state["locked_until"] = time.time() + self.cfg.VAULT_LOCK_BASE_S * (2 ** self._state["rounds"])
            self._state["rounds"] += 1
            self._state["fails"] = 0
            log.warning("vault: too many wrong tries, locked for %ds", self.seconds_locked())
        self._save()
        return "bad" if self.seconds_locked() <= 0 else "locked"

    # ------------------------------------------------------------ session
    def unlock(self):
        self._until = time.time() + self.cfg.HIDDEN_IDLE_S

    def touch(self):
        if self.is_unlocked():
            self._until = time.time() + self.cfg.HIDDEN_IDLE_S

    def lock(self):
        self._until = 0.0

    def is_unlocked(self):
        return time.time() < self._until

    # ------------------------------------------------------------ the only way to see the hidden files
    def list_files(self):
        if not self.is_unlocked():
            return []
        from .gallery import EXTS
        d = self.cfg.HIDDEN_DIR
        try:
            fs = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(EXTS)]
        except OSError:
            return []
        return sorted(fs, key=os.path.getmtime, reverse=True)


# =============================================================================== modal screen
class VaultScreen(Screen):
    """Full-screen modal. Modes: unlock | setup. Keypad for a 4-digit PIN; 'Use password' opens the keyboard instead."""
    name, title, accent = "vault", "Hidden vault", PURPLE
    mini = False

    def __init__(self, app):
        super().__init__(app)
        self.mode, self.stage, self.buf, self.first, self.msg = "unlock", "enter", "", "", ""
        self.on_done = None
        self.pressed = ("", 0.0)
        self.shake_t = 0.0

    def enter(self, mode="unlock", on_done=None, **kw):
        self.mode, self.on_done = mode, on_done
        self.stage = "enter" if mode == "unlock" else "new"
        self.buf, self.first, self.msg = "", "", ""
        self.app.vault.mount()

    # ---- layout
    def _keys(self):
        u = self.u
        kw, kh, gap = 104 * u, 62 * u, 12 * u
        x0, y0 = self.w / 2 - (3 * kw + 2 * gap) / 2, 232 * u
        labels = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "X", "0", "<"]
        return {lab: pygame.Rect(int(x0 + (i % 3) * (kw + gap)), int(y0 + (i // 3) * (kh + gap)), int(kw), int(kh)) for i, lab in enumerate(labels)}

    def _pw_rect(self):
        u = self.u
        return pygame.Rect(int(self.w - 250 * u), int(self.h - 84 * u), int(230 * u), int(56 * u))

    def priority_hit(self, pos):
        return False

    def _heading(self):
        if self.mode == "unlock":
            return "Enter PIN"
        return "Create a 4-digit PIN" if self.stage == "new" else "Confirm your PIN"

    # ---- drawing
    @guarded("draw")
    def draw(self, surf):
        u, w = self.u, self.w
        surf.fill(mix(BG, PURPLE, 0.12))
        icon_lock(surf, w / 2, 56 * u, 26 * u, PURPLE)
        t = font(30 * u).render(self._heading(), True, TEXT)
        surf.blit(t, (w / 2 - t.get_width() / 2, 98 * u))
        now = time.time()
        off = math.sin(now * 60) * 12 * u if now < self.shake_t else 0
        for i in range(PIN_LEN):
            c = (int(w / 2 + (i - (PIN_LEN - 1) / 2.0) * 54 * u + off), int(176 * u))
            pygame.draw.circle(surf, PURPLE if i < len(self.buf) else TRACK, c, int(15 * u))
            if i >= len(self.buf):
                pygame.draw.circle(surf, mix(BG, PURPLE, 0.3), c, int(15 * u), 2)
        lock_s = self.app.vault.seconds_locked()
        if lock_s > 0:
            msg, col = "Too many tries. Wait %ds" % math.ceil(lock_s), RED
        else:
            msg, col = (self.msg or "Type the PIN on the keypad"), (RED if self.msg else MUTED)
        m = font(20 * u).render(msg, True, col)
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
        r = self._pw_rect()
        button(surf, r, BLUE)
        self.text(surf, "Use password", r.centerx, r.centery - 11 * u, 20, TEXT, center=True)
        b = self.back_rect()
        button(surf, b, TEXT)
        icon_arrow(surf, b.centerx, b.centery, 18 * u, TEXT, True)

    # ---- input
    def on_back(self):
        self._finish("cancel")

    def _finish(self, res):
        cb = self.on_done
        self.on_done = None
        self.app.back()
        if cb:
            try:
                cb(res)
            except Exception:
                log.exception("vault callback failed")

    @guarded("on_down")
    def on_down(self, pos):
        v = self.app.vault
        if inside(pos, self._pw_rect()):
            self._password_flow()
            return
        now = time.time()
        for lab, r in self._keys().items():
            if not inside(pos, r):
                continue
            self.pressed = (lab, now)
            if v.seconds_locked() > 0 and self.mode == "unlock":
                return
            if lab == "X":
                self._finish("cancel")
            elif lab == "<":
                self.buf = self.buf[:-1]
            else:
                if len(self.buf) < PIN_LEN:
                    self.buf += lab
                if len(self.buf) == PIN_LEN:
                    self._submit(self.buf)
            return

    def _submit(self, secret):
        v = self.app.vault
        if self.mode == "unlock":
            res = v.verify(secret)
            if res == "ok":
                self._finish("unlocked")
                return
            self.buf = ""
            self.shake_t = time.time() + 0.4
            self.msg = "Wrong PIN" if res == "bad" else ""
            if res == "locked":
                self.app.toast("Vault locked for %d seconds" % math.ceil(v.seconds_locked()), 3)
            return
        if self.stage == "new":
            self.first, self.buf, self.stage, self.msg = secret, "", "confirm", ""
        elif secret != self.first:
            self.buf, self.stage, self.first, self.msg = "", "new", "", "PINs did not match - start again"
            self.shake_t = time.time() + 0.4
        else:
            v.set_secret(secret)
            v.unlock()
            self._finish("pin_set")

    # ---- alphanumeric password through the on-screen keyboard
    def _password_flow(self):
        a, v = self.app, self.app.vault
        cb = self.on_done
        self.on_done = None
        if self.mode == "unlock":
            def got(text):
                if text is None:
                    self.on_done = cb
                    return
                res = v.verify(text)
                if res == "ok":
                    if cb:
                        cb("unlocked")
                else:
                    a.toast("Wrong password" if res == "bad" else "Too many tries - wait %ds" % math.ceil(v.seconds_locked()), 3)
                    if cb:
                        cb("failed" if res == "bad" else "locked")
            a.back()
            a.ask_text("Vault password", "", got, password=True, hint="letters and numbers")
        else:
            def first(text):
                if not text:
                    if cb:
                        cb("cancel")
                    return
                if len(text) < PIN_LEN:
                    a.toast("Use at least 4 characters", 3)
                    if cb:
                        cb("cancel")
                    return

                def second(t2):
                    if t2 == text and v.set_secret(text):
                        v.unlock()
                        if cb:
                            cb("pin_set")
                    else:
                        a.toast("Passwords did not match", 3)
                        if cb:
                            cb("cancel")
                a.ask_text("Confirm password", "", second, password=True)
            a.back()
            a.ask_text("Create a vault password", "", first, password=True, hint="at least 4 characters")

    def context(self):
        return "A secure keypad for the hidden vault is on the screen. I never look at or say the PIN."
