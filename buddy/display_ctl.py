"""Screen brightness: real backlight if there is one, otherwise a software dimming overlay."""
import glob
import logging
import os
import shutil
import subprocess

import pygame

log = logging.getLogger("display")


class DisplayControl:
    def __init__(self, cfg, simulate=False):
        self.level = 100
        self.sim = simulate
        self.mode = "software"
        self._overlay = None
        if not simulate:
            if shutil.which("brightnessctl"):
                self.mode = "brightnessctl"
            elif glob.glob("/sys/class/backlight/*/brightness") and os.access(glob.glob("/sys/class/backlight/*/brightness")[0], os.W_OK):
                self.mode = "sysfs"

    def set(self, level):
        self.level = int(max(10, min(100, level)))
        try:
            if self.mode == "brightnessctl":
                subprocess.run(["brightnessctl", "set", "%d%%" % self.level], capture_output=True, timeout=3)
            elif self.mode == "sysfs":
                d = os.path.dirname(glob.glob("/sys/class/backlight/*/brightness")[0])
                mx = int(open(os.path.join(d, "max_brightness")).read())
                open(os.path.join(d, "brightness"), "w").write(str(int(mx * self.level / 100)))
        except Exception as e:
            log.info("hardware brightness failed (%s) - using software dimming", e)
            self.mode = "software"

    def describe(self):
        return {"brightnessctl": "Backlight", "sysfs": "Backlight"}.get(self.mode, "Software dimming (this HDMI screen has no backlight control)")

    def apply_overlay(self, screen):
        """Software dimming: darken everything by drawing a black layer with alpha."""
        if self.mode != "software" or self.level >= 100:
            return
        size = screen.get_size()
        if self._overlay is None or self._overlay.get_size() != size:
            self._overlay = pygame.Surface(size)
            self._overlay.fill((0, 0, 0))
        self._overlay.set_alpha(int((100 - self.level) / 100.0 * 215))
        screen.blit(self._overlay, (0, 0))
