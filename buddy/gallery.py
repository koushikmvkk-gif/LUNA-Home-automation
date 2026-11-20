"""Photo storage: normal gallery, hidden (PIN protected) gallery, PIN handling."""
import hashlib
import hmac
import json
import logging
import os
import shutil
import time

log = logging.getLogger("gallery")
VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v")
EXTS = (".jpg", ".jpeg", ".png") + VIDEO_EXTS


class GalleryStore:
    def __init__(self, cfg):
        self.cfg = cfg
        for d in (cfg.GALLERY_DIR, cfg.HIDDEN_DIR):
            os.makedirs(d, exist_ok=True)

    def dir_for(self, hidden):
        return self.cfg.HIDDEN_DIR if hidden else self.cfg.GALLERY_DIR

    def new_photo_path(self):
        return os.path.join(self.cfg.GALLERY_DIR, "IMG_%s.jpg" % time.strftime("%Y%m%d_%H%M%S"))

    def new_video_path(self):
        return os.path.join(self.cfg.GALLERY_DIR, "VID_%s.mp4" % time.strftime("%Y%m%d_%H%M%S"))

    def list(self, hidden=False):
        d = self.dir_for(hidden)
        files = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(EXTS)]
        return sorted(files, key=os.path.getmtime, reverse=True)       # newest first

    def latest(self, videos=False):
        files = [f for f in self.list(False) if f.lower().endswith(VIDEO_EXTS) == videos]
        return files[0] if files else None

    def delete(self, path):
        try:
            os.remove(path)
            return True
        except OSError:
            return False

    def move(self, path, to_hidden):
        dest = os.path.join(self.dir_for(to_hidden), os.path.basename(path))
        try:
            shutil.move(path, dest)
            return dest
        except OSError as e:
            log.warning("move failed: %s", e)
            return None


class PinStore:
    """4-digit PIN for the hidden gallery. Only a salted PBKDF2 hash is stored - never the PIN itself."""

    def __init__(self, cfg, path=None):
        self.path = path or cfg.PIN_FILE
        self._data = None
        self._load()

    def _load(self):
        try:
            with open(self.path) as f:
                self._data = json.load(f)
        except Exception:
            self._data = None

    def is_set(self):
        return bool(self._data)

    @staticmethod
    def _hash(pin, salt):
        return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 150_000)

    def set(self, pin):
        salt = os.urandom(16)
        self._data = {"salt": salt.hex(), "hash": self._hash(pin, salt).hex()}
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self._data, f)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def verify(self, pin):
        if not self._data:
            return False
        h = self._hash(pin, bytes.fromhex(self._data["salt"]))
        return hmac.compare_digest(h.hex(), self._data["hash"])
