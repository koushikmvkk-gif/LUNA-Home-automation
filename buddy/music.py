"""Music library (album folders) + players (mpv through its JSON IPC socket, or a simulator)."""
import difflib
import json
import logging
import os
import random
import re
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass

log = logging.getLogger("music")
AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus", ".wma")
FILLER = {"a", "an", "the", "some", "any", "me", "us", "my", "song", "songs", "music", "track", "tracks", "please", "something",
          "play", "from", "album", "folder", "file", "of", "by", "called", "named", "titled", "playlist", "to", "listen", "hear"}


@dataclass
class Track:
    title: str
    path: str
    album: str


def norm(s):
    s = os.path.splitext(s)[0] if s.lower().endswith(AUDIO_EXTS) else s
    s = re.sub(r"^\s*\d{1,3}\s*[-_.)]*\s*", "", s)
    s = re.sub(r"[\[(].*?[\])]", " ", s)
    s = re.sub(r"[_\-.]+", " ", s.lower())
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def score(query, title):
    q, t = norm(query), norm(title)
    if not q or not t:
        return 0.0
    if q == t:
        return 1.0
    if q in t:
        return 0.88 + 0.12 * len(q) / len(t)
    qt, tt = q.split(), t.split()
    overlap = sum(1 for w in qt if w in tt) / float(len(qt))
    close = sum(1 for w in qt if difflib.get_close_matches(w, tt, n=1, cutoff=0.8)) / float(len(qt))
    ratio = difflib.SequenceMatcher(None, q, t).ratio()
    return max(0.9 * overlap, 0.8 * close, ratio * 0.95)


class MusicLibrary:
    def __init__(self, cfg):
        self.cfg = cfg
        self.root = cfg.MUSIC_DIR
        os.makedirs(self.root, exist_ok=True)
        for name in cfg.MUSIC_ALIASES:
            os.makedirs(os.path.join(self.root, name), exist_ok=True)

    def albums(self):
        names = [d for d in os.listdir(self.root) if os.path.isdir(os.path.join(self.root, d)) and not d.startswith(".")]
        order = list(self.cfg.MUSIC_ALIASES)
        return sorted(names, key=lambda n: (order.index(n) if n in order else 99, n.lower()))

    def tracks(self, album):
        d = os.path.join(self.root, album)
        try:
            files = sorted(f for f in os.listdir(d) if f.lower().endswith(AUDIO_EXTS))
        except OSError:
            return []
        return [Track(norm(f).title() or f, os.path.join(d, f), album) for f in files]

    def all_tracks(self):
        out = []
        for a in self.albums():
            out += self.tracks(a)
        return out

    def count(self, album):
        return len(self.tracks(album))

    def create_album(self, name):
        name = re.sub(r"[^A-Za-z0-9 &'-]", "", name).strip()
        if not name:
            return None
        os.makedirs(os.path.join(self.root, name), exist_ok=True)
        return name

    def delete_album(self, name):
        d = os.path.join(self.root, name)
        if os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
            return True
        return False

    def aliases(self, album):
        words = set(self.cfg.MUSIC_ALIASES.get(album, [])) | set(norm(album).split())
        return words

    def album_from_words(self, words):
        """First album whose name / alias words appear in `words` (a list of lowercase words)."""
        for a in self.albums():
            if any(w in self.aliases(a) for w in words):
                return a
        return None

    def find_track(self, query, album=None):
        pool = self.tracks(album) if album else self.all_tracks()
        best, best_s = None, 0.0
        for t in pool:
            s = score(query, t.title)
            if s > best_s:
                best, best_s = t, s
        return (best, best_s) if best_s >= 0.55 else (None, best_s)

    def resolve(self, album_hint, query):
        """Voice request -> (tracks_to_queue, start_index, description). Empty list if nothing found."""
        words = norm(query).split() if query else []
        core = [w for w in words if w not in FILLER]
        album = None
        if album_hint:
            album = album_hint if album_hint in self.albums() else None
        if album is None and core:
            album = self.album_from_words(core[:2]) or self.album_from_words(core)
        title_words = [w for w in core if not (album and w in self.aliases(album))]
        title_q = " ".join(title_words)
        if title_q:
            for pool_album in ([album] if album else []) + [None]:
                t, s = self.find_track(title_q, pool_album)
                if t:
                    queue = self.tracks(t.album)
                    idx = next((i for i, x in enumerate(queue) if x.path == t.path), 0)
                    return queue, idx, "%s" % t.title
            # a title was asked for but not found anywhere
            return [], 0, title_q
        if album:
            tracks = self.tracks(album)
            if tracks:
                return tracks, random.randrange(len(tracks)), "the %s album" % album
        return [], 0, ""


# --------------------------------------------------------------------------- players
class SimPlayer:
    """Fake player for --sim and tests: keeps time, honours pause / seek / loop."""
    available = True
    kind = "sim"

    def __init__(self, cfg):
        self.queue, self.idx = [], 0
        self.pos, self.dur, self.paused, self.active = 0.0, 180.0, False, False
        self.loop, self.shuffle = "off", False
        self._t = time.time()
        self.volume = 100

    def _advance_time(self):
        now = time.time()
        if self.active and not self.paused:
            self.pos += now - self._t
            if self.pos >= self.dur:
                self.pos = 0.0
                if self.loop == "one":
                    pass
                elif self.idx + 1 < len(self.queue):
                    self.idx += 1
                elif self.loop == "all":
                    self.idx = 0
                else:
                    self.active = False
        self._t = now

    def play_list(self, tracks, index=0):
        self.queue, self.idx, self.pos, self.paused, self.active, self._t = list(tracks), index, 0.0, False, bool(tracks), time.time()

    def toggle(self):
        self._advance_time()
        self.paused = not self.paused

    def pause(self):
        self._advance_time()
        self.paused = True

    def resume(self):
        self._advance_time()
        self.paused = False

    def stop(self):
        self.active, self.queue = False, []

    def next(self):
        if self.queue:
            self.idx = (self.idx + 1) % len(self.queue)
            self.pos = 0.0

    def prev(self):
        if self.queue:
            self.idx = (self.idx - 1) % len(self.queue)
            self.pos = 0.0

    def seek(self, delta):
        self._advance_time()
        self.pos = max(0.0, min(self.dur - 1, self.pos + delta))

    def seek_to(self, frac):
        self.pos = max(0.0, min(self.dur - 1, self.dur * frac))

    def set_loop(self, mode):
        self.loop = mode

    def duck(self, on):
        self.volume = 35 if on else 100

    def status(self):
        self._advance_time()
        t = self.queue[self.idx] if self.queue and self.active else None
        return dict(active=self.active, playing=self.active and not self.paused, title=t.title if t else "", album=t.album if t else "",
                    pos=self.pos, dur=self.dur, index=self.idx, count=len(self.queue), loop=self.loop)


class MpvPlayer:
    """Audio playback with mpv (started once in idle mode, controlled over a unix socket)."""
    kind = "mpv"

    def __init__(self, cfg):
        self.cfg = cfg
        self.sock_path = "/tmp/luna_music.sock"
        self.proc = None
        self.available = shutil.which(cfg.MPV) is not None
        self.queue, self.idx, self.loop = [], 0, "off"
        self.lock = threading.Lock()
        self._st = dict(active=False, playing=False, title="", album="", pos=0.0, dur=0.0, index=0, count=0, loop="off")
        self._ducked = False
        if self.available:
            threading.Thread(target=self._poll, daemon=True, name="mpv-poll").start()

    def _ensure(self):
        if self.proc and self.proc.poll() is None:
            return True
        try:
            if os.path.exists(self.sock_path):
                os.remove(self.sock_path)
            self.proc = subprocess.Popen([self.cfg.MPV, "--no-video", "--idle=yes", "--force-window=no", "--really-quiet",
                                          "--input-ipc-server=" + self.sock_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(30):
                if os.path.exists(self.sock_path):
                    return True
                time.sleep(0.1)
        except Exception as e:
            log.warning("cannot start mpv: %s", e)
        return False

    def _cmd(self, *args):
        with self.lock:
            if not self._ensure():
                return None
            try:
                s = socket.socket(socket.AF_UNIX)
                s.settimeout(1.5)
                s.connect(self.sock_path)
                s.sendall((json.dumps({"command": list(args)}) + "\n").encode())
                buf = b""
                while b"\n" not in buf:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                s.close()
                for line in buf.split(b"\n"):
                    if line.strip():
                        d = json.loads(line)
                        if "error" in d:
                            return d.get("data")
            except Exception:
                return None
        return None

    def _poll(self):
        while True:
            time.sleep(0.5)
            if not (self.proc and self.proc.poll() is None):
                self._st["active"] = False
                continue
            idle = self._cmd("get_property", "idle-active")
            if idle:
                self._st.update(active=False, playing=False)
                continue
            pos, dur, paused, ppos = (self._cmd("get_property", k) for k in ("time-pos", "duration", "pause", "playlist-pos"))
            if isinstance(ppos, int) and 0 <= ppos < len(self.queue):
                self.idx = ppos
            t = self.queue[self.idx] if self.queue and self.idx < len(self.queue) else None
            self._st.update(active=True, playing=not paused, title=t.title if t else "", album=t.album if t else "",
                            pos=float(pos or 0), dur=float(dur or 0), index=self.idx, count=len(self.queue), loop=self.loop)

    def play_list(self, tracks, index=0):
        self.queue, self.idx = list(tracks), index
        if not tracks or not self._ensure():
            return
        self._cmd("loadfile", tracks[index].path, "replace")
        for t in tracks[index + 1:] + tracks[:index]:
            self._cmd("loadfile", t.path, "append")
        self.idx = 0 if False else index
        self.queue = tracks[index:] + tracks[:index]
        self.idx = 0
        self.set_loop(self.loop)
        self._cmd("set_property", "pause", False)
        self._st.update(active=True, playing=True)

    def toggle(self):
        self._cmd("cycle", "pause")

    def pause(self):
        self._cmd("set_property", "pause", True)

    def resume(self):
        self._cmd("set_property", "pause", False)

    def stop(self):
        self._cmd("stop")
        self.queue = []
        self._st.update(active=False, playing=False)

    def next(self):
        self._cmd("playlist-next", "weak")

    def prev(self):
        self._cmd("playlist-prev", "weak")

    def seek(self, delta):
        self._cmd("seek", delta, "relative")

    def seek_to(self, frac):
        self._cmd("seek", frac * 100, "absolute-percent")

    def set_loop(self, mode):
        self.loop = mode
        self._cmd("set_property", "loop-file", "inf" if mode == "one" else "no")
        self._cmd("set_property", "loop-playlist", "inf" if mode == "all" else "no")

    def duck(self, on):
        if on != self._ducked:
            self._ducked = on
            self._cmd("set_property", "volume", 35 if on else 100)

    def status(self):
        return dict(self._st, loop=self.loop)


def make_player(cfg, simulate=False):
    if simulate:
        return SimPlayer(cfg)
    p = MpvPlayer(cfg)
    return p
