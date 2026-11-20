"""
USB webcam + face recognition.

Real implementation: OpenCV (YuNet face detector + SFace recognizer, both small ONNX models,
fast enough for a Pi 4). Everything runs on the Pi - no pictures leave the device.
`SimCamera` is a stand-in used by `main.py --sim`.
"""
import logging
import os
import queue
import random
import threading
import time

from .people import RANK_UNKNOWN, clean_name, LEAST

log = logging.getLogger("camera")
YUNET = "face_detection_yunet_2023mar.onnx"
SFACE = "face_recognition_sface_2021dec.onnx"


class CameraBase:
    """Shared bookkeeping: who is visible, arrival / unknown events, priority selection."""

    def __init__(self, cfg, people):
        self.cfg, self.people = cfg, people
        self.available = False
        self.recognition = False
        self.status = "starting"
        self.events = queue.Queue()
        self._vis = []                      # dicts: name, person, rank, score, area, t
        self._vlock = threading.Lock()
        self._last_seen, self._streak, self._prev_seen = {}, {}, {}
        self._unknown_streak, self._last_unknown_evt = 0, 0.0
        self.recording, self.rec_start, self.rec_path = False, 0.0, None

    REC_FPS = 15

    # ------------------------------------------------------------ results
    def _publish(self, dets, now):
        with self._vlock:
            self._vis = dets
        seen = set()
        for d in dets:
            if d["person"]:
                n = d["name"]
                seen.add(n)
                self._streak[n] = self._streak.get(n, 0) + 1
                if self._streak[n] == 1:
                    self._prev_seen[n] = self._last_seen.get(n, 0)
                if self._streak[n] == 2 and now - self._prev_seen.get(n, 0) > self.cfg.AWAY_S:
                    self.events.put(("arrive", n))
                self._last_seen[n] = now
                self.people.add_sample(d["person"], d["feature"]) if d.get("feature") is not None and d["score"] > 0.55 else None
        for n in list(self._streak):
            if n not in seen:
                self._streak[n] = 0
        if any(not d["person"] for d in dets):
            self._unknown_streak += 1
            if self._unknown_streak >= 3 and now - self._last_unknown_evt > 20:
                self._last_unknown_evt = now
                self.events.put(("unknown", None))
        else:
            self._unknown_streak = 0

    def visible(self, max_age=None):
        max_age = self.cfg.PERSON_STICKY_S if max_age is None else max_age
        now = time.time()
        with self._vlock:
            return [d for d in self._vis if now - d["t"] <= max_age]

    def current_person(self, max_age=None):
        """Highest-priority recognised person in view (ties: the biggest / closest face)."""
        known = [d for d in self.visible(max_age) if d["person"]]
        if not known:
            return None, RANK_UNKNOWN
        best = min(known, key=lambda d: (d["rank"], -d["area"]))
        return best["person"], best["rank"]

    def unknown_visible(self, max_age=None):
        return any(not d["person"] for d in self.visible(max_age))

    def visible_names(self, max_age=None):
        return sorted({d["name"] for d in self.visible(max_age) if d["person"]})

    # to be provided by subclasses
    def preview_surface(self, mirror=True):
        return None

    def capture_jpeg(self, path):
        return False

    def enroll(self, name, tier=LEAST, samples=None, step_s=0.6, progress=None, replace=False):
        return "no_camera", None

    def embed_file(self, path):
        return None

    def start_recording(self, path):
        return False

    def stop_recording(self):
        return None


class CameraService(CameraBase, threading.Thread):
    def __init__(self, cfg, people):
        CameraBase.__init__(self, cfg, people)
        threading.Thread.__init__(self, daemon=True, name="camera")
        self.cv2 = None
        self.detector = self.recognizer = None
        self._frame, self._frame_t = None, 0.0
        self._flock = threading.Lock()
        self._infer = threading.Lock()
        self._pv_cache = (0.0, None)
        self._writer = None
        self._rec_next = 0.0

    # -------------------------------------------------------------- setup
    def _load_models(self):
        cv2, d = self.cv2, self.cfg.FACE_MODEL_DIR
        yn, sf = os.path.join(d, YUNET), os.path.join(d, SFACE)
        if not (os.path.exists(yn) and os.path.exists(sf)):
            log.warning("face models missing in %s - run scripts/download_face_models.sh", d)
            return False
        try:
            self.detector = cv2.FaceDetectorYN.create(yn, "", (320, 240), 0.8, 0.3, 5000)
            self.recognizer = cv2.FaceRecognizerSF.create(sf, "")
            return True
        except Exception as e:
            log.error("cannot load face models: %s", e)
            return False

    def _open(self):
        cv2 = self.cv2
        idxs = [self.cfg.CAMERA_INDEX] if self.cfg.CAMERA_INDEX is not None else [0, 1, 2, 3]
        for i in idxs:
            cap = cv2.VideoCapture(i, cv2.CAP_V4L2)
            if not cap.isOpened():
                cap.release()
                continue
            w, h = self.cfg.CAMERA_SIZE
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            ok, frame = cap.read()
            if ok and frame is not None:
                log.info("camera opened: /dev/video%s %s", i, frame.shape)
                return cap
            cap.release()
        return None

    # ---------------------------------------------------------- inference
    def _detect(self, frame):
        cv2 = self.cv2
        h, w = frame.shape[:2]
        scale = w / 320.0
        small = cv2.resize(frame, (320, int(h / scale)))
        with self._infer:
            self.detector.setInputSize((small.shape[1], small.shape[0]))
            _, faces = self.detector.detect(small)
        if faces is None:
            return []
        faces = faces.copy()
        faces[:, :14] *= scale
        return sorted(faces, key=lambda r: -(r[2] * r[3]))[:4]

    def _feature(self, frame, row):
        with self._infer:
            return self.recognizer.feature(self.recognizer.alignCrop(frame, row))[0]

    def _process(self, frame):
        now = time.time()
        dets = []
        for row in self._detect(frame):
            feat = self._feature(frame, row)
            person, score = self.people.match(feat)
            dets.append(dict(name=person["name"] if person else "?", person=person,
                             rank=self.people.rank(person), score=score,
                             area=float(row[2] * row[3]), t=now, feature=feat))
        self._publish(dets, now)

    # --------------------------------------------------------------- loop
    def run(self):
        if not self.cfg.CAMERA_ENABLED:
            self.status = "camera disabled"
            return
        try:
            import cv2
            self.cv2 = cv2
        except Exception as e:
            self.status = "opencv missing"
            log.error("OpenCV not available: %s (sudo apt install python3-opencv)", e)
            return
        self.recognition = self._load_models()
        last = 0.0
        while True:
            cap = self._open()
            if cap is None:
                self.available, self.status = False, "no camera"
                time.sleep(5)
                continue
            self.available = True
            self.status = "faces on" if self.recognition else "camera only (no face models)"
            fails = 0
            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
                    fails += 1
                    if fails > 20:
                        break
                    time.sleep(0.05)
                    continue
                fails = 0
                with self._flock:
                    self._frame, self._frame_t = frame, time.time()
                if self.recording and self._writer is not None and time.time() >= self._rec_next:
                    self._rec_next = max(self._rec_next + 1.0 / self.REC_FPS, time.time() - 0.2) if self._rec_next else time.time() + 1.0 / self.REC_FPS
                    try:
                        self._writer.write(frame)
                    except Exception:
                        pass
                if self.recognition and time.time() - last >= self.cfg.FACE_INTERVAL_S:
                    last = time.time()
                    try:
                        self._process(frame)
                    except Exception as e:
                        log.warning("face processing error: %s", e)
                time.sleep(0.02)
            cap.release()
            self.available, self.status = False, "camera lost"
            log.warning("camera lost - reopening")

    # ----------------------------------------------------------- public API
    def _latest(self):
        with self._flock:
            return (None, 0.0) if self._frame is None else (self._frame.copy(), self._frame_t)

    def preview_surface(self, mirror=True):
        if not self.available:
            return None
        import pygame
        frame, ft = self._latest()
        if frame is None or time.time() - ft > 2:
            return None
        if self._pv_cache[0] == ft and self._pv_cache[1] is not None:
            return self._pv_cache[1]
        cv2 = self.cv2
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        if mirror:
            rgb = cv2.flip(rgb, 1)
        surf = pygame.image.frombuffer(rgb.tobytes(), (rgb.shape[1], rgb.shape[0]), "RGB")
        self._pv_cache = (ft, surf)
        return surf

    def capture_jpeg(self, path, caption=None):
        frame, ft = self._latest()
        if frame is None or time.time() - ft > 2:
            return False
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if caption:
            cv2 = self.cv2
            h = frame.shape[0]
            cv2.rectangle(frame, (0, h - 34), (frame.shape[1], h), (0, 0, 0), -1)
            cv2.putText(frame, caption, (8, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
        return bool(self.cv2.imwrite(path, frame, [self.cv2.IMWRITE_JPEG_QUALITY, 92]))

    def collect(self, n, step_s, progress=None, allow=None):
        """Take n face samples. allow = a person's name whose face may also be used (retake / add photos).
        Returns (status, feats, jpgs, known_name)."""
        import numpy as np
        if not self.available:
            return "no_camera", [], [], None
        if not self.recognition:
            return "no_model", [], [], None
        feats, jpgs, known_seen, last_t, next_at = [], [], None, 0.0, 0.0
        deadline = time.time() + 12 + n * (step_s + 2.5)
        while len(feats) < n and time.time() < deadline:
            if time.time() < next_at:
                time.sleep(0.05)
                continue
            frame, ft = self._latest()
            if frame is None or ft == last_t or time.time() - ft > 2:
                time.sleep(0.1)
                continue
            last_t = ft
            try:
                rows = self._detect(frame)
            except Exception:
                rows = []
            cands = []
            for row in rows:
                feat = self._feature(frame, row)
                person, _ = self.people.match(feat)
                cands.append((row, feat, person))
            ok = [c for c in cands if c[2] is None or (allow and c[2]["name"] == allow)]
            if ok:
                if progress:
                    progress(len(feats), n)
                row, feat, _ = ok[0]
                feats.append(feat)
                jpgs.append(self._thumb(frame, row))
                next_at = time.time() + step_s
            elif cands:
                known_seen = cands[0][2]["name"]
        if len(feats) < max(1, min(n, 3)):
            return ("known" if known_seen else "no_face"), [], [], known_seen
        arr = np.array(feats)
        arr = arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9)
        mean = arr.mean(axis=0)
        if float((arr @ mean / (np.linalg.norm(mean) + 1e-9)).min()) < 0.45:
            return "no_face", [], [], None
        return "ok", feats, jpgs, None

    def enroll(self, name, tier=LEAST, samples=None, step_s=0.6, progress=None, replace=False):
        """Learn the face in front of the camera. Returns (status, info)."""
        name = clean_name(name)
        n = samples or self.people.target_samples(tier)
        st, feats, jpgs, known = self.collect(n, step_s, progress, allow=name if replace else None)
        if st != "ok":
            return st, known
        try:
            if replace:
                self.people.replace_photos(name, feats, jpgs)
                return "ok", self.people.get(name)
            return "ok", self.people.enroll(name, feats, tier=tier, jpgs=jpgs)
        except ValueError as e:
            return str(e), name

    def add_samples(self, name, n, step_s=1.2, progress=None):
        st, feats, jpgs, known = self.collect(n, step_s, progress, allow=name)
        if st != "ok":
            return st, known
        try:
            self.people.add_photos(name, feats, jpgs)
            return "ok", self.people.get(name)
        except ValueError as e:
            return str(e), name

    def embed_file(self, path):
        """Fingerprint + face crop from a saved picture (for adding photos manually). None if no single clear face."""
        if not self.recognition:
            return None
        img = self.cv2.imread(path)
        if img is None:
            return None
        try:
            rows = self._detect(img)
            if not rows:
                return None
            return self._feature(img, rows[0]), self._thumb(img, rows[0])
        except Exception:
            return None

    # ---- video recording
    def start_recording(self, path):
        if not self.available or self.recording:
            return False
        frame, _ = self._latest()
        if frame is None:
            return False
        cv2 = self.cv2
        h, w = frame.shape[:2]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), self.REC_FPS, (w, h))
        if not self._writer.isOpened():
            self._writer = None
            return False
        self.recording, self.rec_start, self._rec_next, self.rec_path = True, time.time(), 0.0, path
        return True

    def stop_recording(self):
        if not self.recording:
            return None
        self.recording = False
        try:
            self._writer.release()
        except Exception:
            pass
        self._writer = None
        return self.rec_path

    def _thumb(self, frame, row):
        cv2 = self.cv2
        x, y, w, h = [int(v) for v in row[:4]]
        m = int(0.25 * max(w, h))
        x0, y0 = max(0, x - m), max(0, y - m)
        crop = frame[y0:y + h + m, x0:x + w + m]
        if crop.size == 0:
            return None
        crop = cv2.resize(crop, (160, int(160 * crop.shape[0] / crop.shape[1])))
        ok, buf = cv2.imencode(".jpg", crop)
        return buf.tobytes() if ok else None


class SimCamera(CameraBase):
    """Fake camera for `--sim`: control who is 'in view' from the terminal ( !see Name1,Name2 / !unknown / !none )."""

    def __init__(self, cfg, people):
        super().__init__(cfg, people)
        self.available = self.recognition = True
        self.status = "simulated"
        self.names, self.unknown = [], False
        self.t0 = time.time()

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="simcam").start()

    def _loop(self):
        while True:
            now = time.time()
            dets = []
            for n in self.names:
                p = self.people.get(n)
                if p:
                    dets.append(dict(name=p["name"], person=p, rank=self.people.rank(p), score=0.9,
                                     area=1000.0 + random.random(), t=now, feature=None))
            if self.unknown:
                dets.append(dict(name="?", person=None, rank=RANK_UNKNOWN, score=0.0, area=900.0, t=now, feature=None))
            self._publish(dets, now)
            time.sleep(0.3)

    def set_view(self, names=(), unknown=False):
        self.names, self.unknown = list(names), unknown

    def preview_surface(self, mirror=True):
        import pygame
        s = pygame.Surface(self.cfg.CAMERA_SIZE)
        w, h = self.cfg.CAMERA_SIZE
        for y in range(0, h, 8):
            pygame.draw.rect(s, (40 + y * 90 // h, 90, 160 - y * 80 // h), pygame.Rect(0, y, w, 8))
        pygame.draw.circle(s, (240, 200, 170), (w // 2, h // 2), 90)
        pygame.draw.circle(s, (30, 30, 30), (w // 2 - 30, h // 2 - 15), 10)
        pygame.draw.circle(s, (30, 30, 30), (w // 2 + 30, h // 2 - 15), 10)
        return s

    def capture_jpeg(self, path, caption=None):
        import pygame
        os.makedirs(os.path.dirname(path), exist_ok=True)
        pygame.image.save(self.preview_surface(), path)
        return True

    def enroll(self, name, tier=LEAST, samples=None, step_s=0.6, progress=None, replace=False):
        import random as r
        if not self.unknown and not self.names:
            return "no_face", None
        if not self.unknown and not replace:
            return "known", self.names[0]
        n = samples or self.people.target_samples(tier)
        feats = []
        for k in range(n):
            if progress:
                progress(k, n)
            feats.append([r.uniform(-1, 1) for _ in range(128)])
            time.sleep(0.05)
        try:
            if replace:
                self.people.replace_photos(name, feats, [b"x"] * n)
                rec = self.people.get(name)
            else:
                rec = self.people.enroll(name, feats, tier=tier, jpgs=[b"x"] * n)
        except ValueError as e:
            return str(e), clean_name(name)
        self.unknown = False
        if rec["name"] not in self.names:
            self.names.append(rec["name"])
        return "ok", rec

    def embed_file(self, path):
        import random as r
        return [r.uniform(-1, 1) for _ in range(128)], b"x"

    def add_samples(self, name, n, step_s=1.2, progress=None):
        import random as r
        feats = []
        for k in range(n):
            if progress:
                progress(k, n)
            feats.append([r.uniform(-1, 1) for _ in range(128)])
            time.sleep(0.03)
        try:
            self.people.add_photos(name, feats, [b"x"] * n)
        except ValueError as e:
            return str(e), name
        return "ok", self.people.get(name)

    def start_recording(self, path):
        if self.recording:
            return False
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.recording, self.rec_start, self.rec_path = True, time.time(), path
        return True

    def stop_recording(self):
        if not self.recording:
            return None
        self.recording = False
        with open(self.rec_path, "wb") as f:
            f.write(b"SIMVIDEO")
        return self.rec_path
