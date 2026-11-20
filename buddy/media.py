"""Videos (movies + camera recordings): library, thumbnails, mpv playback, USB import."""
import glob
import hashlib
import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time

from .music import AUDIO_EXTS, norm, score

log = logging.getLogger("media")
VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".mpg", ".mpeg", ".wmv")


def is_video(path):
    return path.lower().endswith(VIDEO_EXTS)


class VideoLibrary:
    def __init__(self, cfg):
        self.cfg = cfg
        os.makedirs(cfg.MOVIES_DIR, exist_ok=True)
        os.makedirs(cfg.THUMB_DIR, exist_ok=True)

    def movies(self):
        try:
            files = [os.path.join(self.cfg.MOVIES_DIR, f) for f in os.listdir(self.cfg.MOVIES_DIR) if f.lower().endswith(VIDEO_EXTS)]
        except OSError:
            return []
        return sorted(files, key=lambda p: os.path.basename(p).lower())

    def gallery_videos(self, store):
        return [p for p in store.list(False) if is_video(p)]

    def title(self, path):
        return norm(os.path.splitext(os.path.basename(path))[0]).title() or os.path.basename(path)

    def find(self, query, store=None):
        pool = self.movies() + (self.gallery_videos(store) if store else [])
        best, best_s = None, 0.0
        for p in pool:
            s = score(query, self.title(p))
            if s > best_s:
                best, best_s = p, s
        return best if best_s >= 0.55 else None

    def thumb_path(self, path):
        try:
            key = "%s|%s" % (path, os.path.getmtime(path))
        except OSError:
            return None
        return os.path.join(self.cfg.THUMB_DIR, hashlib.sha1(key.encode()).hexdigest() + ".jpg")

    def thumb(self, path, make=True):
        """Path of a JPEG thumbnail (first moments of the video), or None."""
        tp = self.thumb_path(path)
        if tp and os.path.exists(tp):
            return tp
        if not make or not tp:
            return None
        try:
            import cv2
            cap = cv2.VideoCapture(path)
            n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            if n > 30:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * 0.1))
            ok, frame = cap.read()
            cap.release()
            if ok and frame is not None:
                h, w = frame.shape[:2]
                frame = cv2.resize(frame, (320, max(1, int(320 * h / w))))
                cv2.imwrite(tp, frame)
                return tp
        except Exception as e:
            log.info("thumbnail failed for %s: %s", path, e)
        return None


class VideoPlayer:
    """Full-screen playback with mpv. Touch the screen to pause, double-tap to quit. Voice control through the IPC socket."""

    def __init__(self, cfg, simulate=False):
        self.cfg, self.sim = cfg, simulate
        self.sock_path = "/tmp/luna_video.sock"
        self.proc = None
        self.path = None
        self._sim_until = 0.0
        self.available = simulate or shutil.which(cfg.MPV) is not None

    def conf_file(self):
        p = os.path.join(self.cfg.DATA_DIR, "mpv_input.conf")
        with open(p, "w") as f:
            f.write("MBTN_LEFT cycle pause\nMBTN_LEFT_DBL quit\nMBTN_RIGHT quit\nESC quit\nq quit\nSPACE cycle pause\n"
                    "RIGHT seek 10\nLEFT seek -10\nUP seek 60\nDOWN seek -60\n")
        return p

    def play(self, path):
        self.path = path
        if self.sim:
            self._sim_until = time.time() + 3
            return True
        if not self.available:
            return False
        try:
            if os.path.exists(self.sock_path):
                os.remove(self.sock_path)
            self.proc = subprocess.Popen([self.cfg.MPV, "--fullscreen", "--osc=yes", "--hwdec=%s" % getattr(self.cfg, "MPV_HWDEC", "auto"), *getattr(self.cfg, "MPV_EXTRA", []), "--really-quiet",
                                          "--no-input-default-bindings", "--input-conf=" + self.conf_file(),
                                          "--input-ipc-server=" + self.sock_path, path],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception as e:
            log.warning("video start failed: %s", e)
            return False

    def running(self):
        if self.sim:
            return time.time() < self._sim_until
        return bool(self.proc and self.proc.poll() is None)

    def ctl(self, *args):
        if self.sim:
            if args and args[0] == "quit":
                self._sim_until = 0
            return
        try:
            import json as _j
            s = socket.socket(socket.AF_UNIX)
            s.settimeout(1)
            s.connect(self.sock_path)
            s.sendall((_j.dumps({"command": list(args)}) + "\n").encode())
            s.close()
        except Exception:
            pass

    def stop(self):
        self.ctl("quit")
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass


def import_from_usb(cfg):
    """Copy Luna/Music/<Album>/*, Luna/Movies/* from any mounted USB drive. Returns (songs, videos)."""
    roots = []
    for pat in cfg.USB_ROOTS:
        roots += [p for p in glob.glob(pat) if os.path.isdir(p) and (not cfg.USB_REQUIRE_MOUNT or os.path.ismount(p))]
    songs = vids = 0
    for r in roots:
        for base in (r, os.path.join(r, "Luna")):
            md = os.path.join(base, "Music")
            if os.path.isdir(md):
                for album in os.listdir(md):
                    ad = os.path.join(md, album)
                    files = [ad] if not os.path.isdir(ad) else [os.path.join(ad, f) for f in os.listdir(ad)]
                    dest_album = album if os.path.isdir(ad) else "Imported"
                    for fp in files:
                        if fp.lower().endswith(AUDIO_EXTS):
                            d = os.path.join(cfg.MUSIC_DIR, dest_album)
                            os.makedirs(d, exist_ok=True)
                            t = os.path.join(d, os.path.basename(fp))
                            if not os.path.exists(t):
                                shutil.copy2(fp, t)
                                songs += 1
            vd = os.path.join(base, "Movies")
            if os.path.isdir(vd):
                for f in os.listdir(vd):
                    if f.lower().endswith(VIDEO_EXTS):
                        t = os.path.join(cfg.MOVIES_DIR, f)
                        if not os.path.exists(t):
                            shutil.copy2(os.path.join(vd, f), t)
                            vids += 1
    return songs, vids
