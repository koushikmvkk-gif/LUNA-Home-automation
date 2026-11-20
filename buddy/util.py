import logging
import os
import socket
import threading
import time


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def lerp(a, b, t):
    return a + (b - a) * t


def mix(c1, c2, t):
    """Blend colour c1 -> c2 by t (0..1)."""
    t = clamp(t, 0.0, 1.0)
    return tuple(int(lerp(a, b, t)) for a, b in zip(c1, c2))


def time_greeting(hour=None):
    """Good morning / afternoon / evening / night, from the clock."""
    if hour is None:
        hour = time.localtime().tm_hour
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 17:
        return "Good afternoon"
    if 17 <= hour < 21:
        return "Good evening"
    return "Good night"


def setup_logging(log_dir):
    os.makedirs(log_dir, exist_ok=True)
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handlers = [logging.StreamHandler()]
    try:
        from logging.handlers import RotatingFileHandler
        handlers.append(RotatingFileHandler(os.path.join(log_dir, "buddy.log"),
                                            maxBytes=500_000, backupCount=2))
    except Exception:
        pass
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)


class NetMonitor(threading.Thread):
    """Tiny background thread that keeps `online` up to date."""

    def __init__(self, interval=10, force=None):
        super().__init__(daemon=True, name="net")
        self.online = False
        self.interval = interval
        self.force = force            # True/False to force (simulation), None = real check

    def run(self):
        while True:
            if self.force is not None:
                self.online = self.force
            else:
                self.online = self._check()
            time.sleep(self.interval)

    @staticmethod
    def _check():
        for host in (("1.1.1.1", 53), ("8.8.8.8", 53)):
            try:
                with socket.create_connection(host, timeout=2):
                    return True
            except OSError:
                continue
        return False


def state_load(cfg):
    import json
    try:
        with open(cfg.UI_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def state_save(cfg, **kw):
    import json
    d = state_load(cfg)
    d.update(kw)
    try:
        os.makedirs(os.path.dirname(cfg.UI_STATE_FILE), exist_ok=True)
        with open(cfg.UI_STATE_FILE, "w") as f:
            json.dump(d, f)
    except Exception:
        pass


# ---------------------------------------------------------------- error boundary
import functools as _ft

_elog = logging.getLogger("errors")


def guarded(label="", default=None, say=True):
    """Decorator: never let an exception escape a UI handler. The traceback goes to logs/buddy.log
    and the person sees a small toast. The main event loop keeps running."""
    def deco(fn):
        @_ft.wraps(fn)
        def wrapper(self, *a, **k):
            try:
                return fn(self, *a, **k)
            except Exception:
                _elog.exception("handler %s.%s failed", type(self).__name__, label or fn.__name__)
                app = getattr(self, "app", None)
                if say and app is not None:
                    try:
                        app.toast("Something went wrong - details are in logs/buddy.log", 3.5)
                    except Exception:
                        pass
                return default
        return wrapper
    return deco


def harden(cls, names, default=None):
    """Wrap the named methods of a screen class with `guarded`."""
    for n in names:
        fn = getattr(cls, n, None)
        if fn is not None and not getattr(fn, "_hardened", False):
            w = guarded(n, default)(fn)
            w._hardened = True
            setattr(cls, n, w)
