"""TTP223 capacitive touch pad -> 'tap' / 'double' / 'long' events."""
import logging
import threading
import time

log = logging.getLogger("touch")


class TouchPad:
    LONG_S = 1.2
    DOUBLE_WINDOW_S = 0.45

    def __init__(self, cfg, simulate=False):
        self.events = []
        self._lock = threading.Lock()
        self._down_at = None
        self._long_fired = False
        self._taps = 0
        self._last_up = 0.0
        self.dev = None
        if not simulate:
            try:
                from gpiozero import Button
                # TTP223 output is HIGH when touched -> pull_down, active on HIGH
                self.dev = Button(cfg.TOUCH_GPIO, pull_up=False, bounce_time=0.03)
                self.dev.when_pressed = self.press
                self.dev.when_released = self.release
                log.info("touch sensor ready on GPIO%d", cfg.TOUCH_GPIO)
            except Exception as e:
                log.warning("touch sensor unavailable: %s", e)

    @property
    def down(self):
        return self._down_at is not None

    def press(self):
        with self._lock:
            self._down_at, self._long_fired = time.time(), False

    def release(self):
        with self._lock:
            if self._down_at is None:
                return
            if not self._long_fired:
                self._taps += 1
                self._last_up = time.time()
            self._down_at = None

    def poll(self):
        """Call every frame; returns a list of 'tap' / 'double' / 'long'."""
        now, out = time.time(), []
        with self._lock:
            if self._down_at and not self._long_fired and now - self._down_at >= self.LONG_S:
                self._long_fired = True
                self._taps = 0
                out.append("long")
            if self._taps and self._down_at is None and now - self._last_up > self.DOUBLE_WINDOW_S:
                out.append("double" if self._taps >= 2 else "tap")
                self._taps = 0
        return out
