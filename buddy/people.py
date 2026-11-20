"""
People database kept in THREE priority files (data/priority/):

    1_masters.json          tier "master"    rank 0   max 6 people,  exactly 10 photos each
    2_priority.json         tier "priority"  rank 1   max 10 people, 1-5 photos each
    3_least_priority.json   tier "least"     rank 3   unlimited people (everyone introduced by voice lands here)

Everyone else (unknown face / nobody in view) has rank 4.
Each person keeps one face "fingerprint" (128 numbers) per photo plus the small face photos themselves
(data/faces/<name>/NN.jpg) so you can see and manage them in Settings > Privacy.
"""
import difflib
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time

log = logging.getLogger("people")

MASTER, PRIORITY, LEAST, UNKNOWN = "master", "priority", "least", "unknown"
FILES = {MASTER: "1_masters.json", PRIORITY: "2_priority.json", LEAST: "3_least_priority.json"}
RANK_UNKNOWN = 4
MAX_EXTRA = 10
TIER_LABEL = {MASTER: "Master (1st priority)", PRIORITY: "Priority (2nd)", LEAST: "Least priority (3rd)"}


def rank_of(tier, level=2):
    return {MASTER: 0, PRIORITY: 1, LEAST: 3}.get(tier, RANK_UNKNOWN)


def rank_label(rank):
    return {0: "master", 1: "priority", 2: "priority", 3: "least priority"}.get(rank, "guest")


def clean_name(name):
    name = re.sub(r"[^A-Za-z ]", "", name or "").strip()
    return " ".join(w.capitalize() for w in name.split())[:30]


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "person"


class PeopleStore:
    def __init__(self, cfg):
        self.cfg = cfg
        self.dir = os.path.join(cfg.DATA_DIR, "priority")
        self.faces_dir = os.path.join(cfg.DATA_DIR, "faces")
        self.threshold = cfg.FACE_MATCH_THRESHOLD
        os.makedirs(self.dir, exist_ok=True)
        os.makedirs(self.faces_dir, exist_ok=True)
        self.lock = threading.RLock()
        self.people = []
        self._last_sample = {}
        self.load()

    # ---- limits
    def max_people(self, tier):
        return {MASTER: self.cfg.MASTER_MAX_PEOPLE, PRIORITY: self.cfg.PRIORITY_MAX_PEOPLE}.get(tier)

    def photo_rule(self, tier):
        """(min, max) number of photos a person of this tier must have."""
        if tier == MASTER:
            return self.cfg.MASTER_PHOTOS, self.cfg.MASTER_PHOTOS
        if tier == PRIORITY:
            return 1, self.cfg.PRIORITY_MAX_PHOTOS
        return 1, 10

    def target_samples(self, tier):
        return self.photo_rule(tier)[1] if tier != LEAST else self.cfg.LEAST_SAMPLES

    def has_room(self, tier, exclude=None):
        m = self.max_people(tier)
        n = len([p for p in self.by_tier(tier) if p is not exclude])
        return m is None or n < m

    # ---- disk
    def load(self):
        with self.lock:
            self.people = []
            for tier, fn in FILES.items():
                try:
                    with open(os.path.join(self.dir, fn)) as f:
                        for p in json.load(f).get("people", []):
                            p["tier"] = tier
                            p.setdefault("embeddings", [])
                            p.setdefault("extra", [])
                            p.setdefault("photos", [])
                            self.people.append(p)
                except FileNotFoundError:
                    pass
                except Exception as e:
                    log.warning("cannot read %s: %s", fn, e)

    def save(self):
        with self.lock:
            for tier, fn in FILES.items():
                data = {"tier": tier,
                        "note": {"master": "1st priority - full control. Max 6 people, exactly 10 photos each.",
                                 "priority": "2nd priority. Max 10 people, up to 5 photos each.",
                                 "least": "3rd priority - newly introduced people. No limit."}[tier],
                        "people": [{k: v for k, v in p.items() if k != "tier"} for p in self.people if p["tier"] == tier]}
                fd, tmp = tempfile.mkstemp(dir=self.dir)
                with os.fdopen(fd, "w") as f:
                    json.dump(data, f)
                os.replace(tmp, os.path.join(self.dir, fn))

    # ---- queries
    def by_tier(self, tier):
        return [p for p in self.people if p["tier"] == tier]

    def has_master(self):
        return bool(self.by_tier(MASTER))

    def names(self):
        return [p["name"] for p in self.people]

    def get(self, name):
        for p in self.people:
            if p["name"].lower() == (name or "").lower():
                return p
        return None

    def find(self, spoken):
        spoken = clean_name(spoken)
        if not spoken:
            return None
        p = self.get(spoken)
        if p:
            return p
        close = difflib.get_close_matches(spoken.lower(), [n.lower() for n in self.names()], n=1, cutoff=0.72)
        return self.get(close[0]) if close else None

    def rank(self, person):
        return rank_of(person["tier"]) if person else RANK_UNKNOWN

    def describe(self, person):
        return rank_label(self.rank(person))

    def photo_count(self, p):
        return len(p["embeddings"])

    def photo_file(self, p, i):
        if i < len(p["photos"]):
            return os.path.join(self.faces_dir, p["photos"][i])
        return None

    def first_photo(self, p):
        f = self.photo_file(p, 0) if p["photos"] else (os.path.join(self.faces_dir, p["thumb"]) if p.get("thumb") else None)
        return f if f and os.path.exists(f) else None

    # ---- matching
    def match(self, feature):
        import numpy as np
        f = np.asarray(feature, dtype="float32").reshape(-1)
        f = f / (np.linalg.norm(f) + 1e-9)
        best, best_s = None, -1.0
        with self.lock:
            for p in self.people:
                for e in list(p["embeddings"]) + list(p["extra"]):
                    e = np.asarray(e, dtype="float32")
                    s = float(np.dot(f, e / (np.linalg.norm(e) + 1e-9)))
                    if s > best_s:
                        best, best_s = p, s
        if best is not None and best_s >= self.threshold:
            return best, best_s
        return None, best_s

    # ---- mutations
    def _write_photos(self, name, jpgs, start=0):
        names = []
        d = os.path.join(self.faces_dir, slug(name))
        os.makedirs(d, exist_ok=True)
        for k, data in enumerate(jpgs):
            fn = "%02d.jpg" % (start + k + 1)
            while os.path.exists(os.path.join(d, fn)) and start == 0 and False:
                pass
            with open(os.path.join(d, fn), "wb") as f:
                f.write(data or b"")
            names.append(slug(name) + "/" + fn)
        return names

    def enroll(self, name, embeddings, tier=LEAST, level=2, jpgs=None):
        name = clean_name(name)
        embs = [[round(float(x), 5) for x in e] for e in embeddings]
        lo, hi = self.photo_rule(tier)
        with self.lock:
            if self.get(name):
                raise ValueError("exists")
            if not self.has_room(tier):
                raise ValueError("full")
            if not (lo <= len(embs) <= hi):
                raise ValueError("photos")
            rec = {"name": name, "added": time.strftime("%Y-%m-%d"), "embeddings": embs, "extra": [],
                   "photos": self._write_photos(name, jpgs) if jpgs else [], "tier": tier}
            self.people.append(rec)
            self.save()
        return rec

    def add_photos(self, name, embeddings, jpgs):
        with self.lock:
            p = self.get(name)
            if not p:
                raise ValueError("unknown")
            lo, hi = self.photo_rule(p["tier"])
            if len(p["embeddings"]) + len(embeddings) > hi:
                raise ValueError("photos")
            start = len(p["photos"])
            p["photos"] += self._write_photos(name, jpgs, start=start) if jpgs else []
            p["embeddings"] += [[round(float(x), 5) for x in e] for e in embeddings]
            self.save()

    def remove_photo(self, name, i):
        with self.lock:
            p = self.get(name)
            if not p or i >= len(p["embeddings"]):
                return False
            lo, hi = self.photo_rule(p["tier"])
            if len(p["embeddings"]) - 1 < lo:
                raise ValueError("photos")
            del p["embeddings"][i]
            if i < len(p["photos"]):
                try:
                    os.remove(os.path.join(self.faces_dir, p["photos"][i]))
                except OSError:
                    pass
                del p["photos"][i]
            self.save()
            return True

    def replace_photos(self, name, embeddings, jpgs):
        with self.lock:
            p = self.get(name)
            if not p:
                raise ValueError("unknown")
            lo, hi = self.photo_rule(p["tier"])
            if not (lo <= len(embeddings) <= hi):
                raise ValueError("photos")
            shutil.rmtree(os.path.join(self.faces_dir, slug(name)), ignore_errors=True)
            p["embeddings"] = [[round(float(x), 5) for x in e] for e in embeddings]
            p["extra"] = []
            p["photos"] = self._write_photos(name, jpgs) if jpgs else []
            self.save()

    def can_move(self, name, tier):
        """(ok, message). Checks capacity and photo rules."""
        p = self.get(name)
        if not p:
            return False, "Unknown person"
        if p["tier"] == tier:
            return False, "Already there"
        if not self.has_room(tier):
            return False, "That level is full (max %s)" % self.max_people(tier)
        lo, hi = self.photo_rule(tier)
        n = len(p["embeddings"])
        if n < lo:
            return False, "Needs %d photos first (has %d)" % (lo, n)
        if p["tier"] == MASTER and len(self.by_tier(MASTER)) <= 1:
            return False, "There must always be one master"
        return True, ("Photos will be trimmed to %d" % hi) if n > hi else ""

    def set_tier(self, name, tier, level=2):
        with self.lock:
            ok, msg = self.can_move(name, tier)
            if not ok:
                raise ValueError(msg)
            p = self.get(name)
            hi = self.photo_rule(tier)[1]
            while len(p["embeddings"]) > hi:
                p["embeddings"].pop()
                if len(p["photos"]) > len(p["embeddings"]):
                    try:
                        os.remove(os.path.join(self.faces_dir, p["photos"][-1]))
                    except OSError:
                        pass
                    p["photos"].pop()
            p["tier"] = tier
            self.save()
            return True

    def forget(self, name, force=False):
        with self.lock:
            p = self.get(name)
            if not p:
                return False
            if not force and p["tier"] == MASTER and len(self.by_tier(MASTER)) <= 1:
                raise ValueError("last master")
            self.people.remove(p)
            shutil.rmtree(os.path.join(self.faces_dir, slug(name)), ignore_errors=True)
            if p.get("thumb"):
                try:
                    os.remove(os.path.join(self.faces_dir, p["thumb"]))
                except OSError:
                    pass
            self.save()
            return True

    def rename(self, old, new):
        with self.lock:
            p = self.get(old)
            new = clean_name(new)
            if not p or not new or (self.get(new) and self.get(new) is not p):
                return False
            old_dir, new_dir = os.path.join(self.faces_dir, slug(p["name"])), os.path.join(self.faces_dir, slug(new))
            if old_dir != new_dir and os.path.isdir(old_dir):
                os.replace(old_dir, new_dir)
                p["photos"] = [slug(new) + "/" + os.path.basename(x) for x in p["photos"]]
            p["name"] = new
            self.save()
            return True

    def add_sample(self, person, feature, every_s=300):
        now = time.time()
        with self.lock:
            if now - self._last_sample.get(person["name"], 0) < every_s:
                return
            self._last_sample[person["name"]] = now
            ex = person["extra"]
            ex.append([round(float(x), 5) for x in feature])
            if len(ex) > MAX_EXTRA:
                del ex[0]
            self.save()
