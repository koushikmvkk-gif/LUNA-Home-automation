"""Security mode: Telegram alerts, siren, security photo log."""
import json
import logging
import math
import os
import struct
import subprocess
import threading
import time
import wave

from .util import state_load, state_save

log = logging.getLogger("security")


class Telegram:
    def __init__(self, cfg):
        self.path = cfg.TELEGRAM_FILE
        self.token, self.chat_id = "", ""
        try:
            with open(self.path) as f:
                d = json.load(f)
            self.token, self.chat_id = d.get("token", ""), str(d.get("chat_id", ""))
        except Exception:
            pass

    def configured(self):
        return bool(self.token and self.chat_id)

    def save(self, token=None, chat_id=None):
        if token is not None:
            self.token = token.strip()
        if chat_id is not None:
            self.chat_id = chat_id.strip()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump({"token": self.token, "chat_id": self.chat_id}, f)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def masked(self, s):
        return "not set" if not s else (s[:4] + "..." + s[-3:] if len(s) > 10 else "***")

    def send_text(self, text):
        if not self.configured():
            return False, "Telegram is not set up"
        try:
            import requests
            r = requests.post("https://api.telegram.org/bot%s/sendMessage" % self.token, data={"chat_id": self.chat_id, "text": text}, timeout=12)
            return r.ok, "Sent" if r.ok else "Telegram error %s" % r.status_code
        except Exception as e:
            return False, "No internet" if "Connection" in type(e).__name__ or "resolve" in str(e).lower() else str(e)[:60]

    def send_photo(self, path, caption):
        if not self.configured():
            return False, "Telegram is not set up"
        try:
            import requests
            with open(path, "rb") as f:
                r = requests.post("https://api.telegram.org/bot%s/sendPhoto" % self.token, data={"chat_id": self.chat_id, "caption": caption},
                                  files={"photo": f}, timeout=25)
            return r.ok, "Sent" if r.ok else "Telegram error %s" % r.status_code
        except Exception as e:
            return False, str(e)[:60]


class Siren:
    """Loud two-tone siren in pulses (so Luna can listen for the intruder's name in the gaps)."""

    ON_S, OFF_S = 4.0, 3.0

    def __init__(self, cfg, simulate=False):
        self.cfg, self.sim = cfg, simulate
        self.active = False       # siren mode on (pulsing)
        self.sounding = False     # currently making noise
        self._proc = None
        self._thread = None
        self.on_gap = None        # callback at the start of each silent gap
        os.makedirs(cfg.DATA_DIR, exist_ok=True)
        self.wav = os.path.join(cfg.DATA_DIR, "siren.wav")

    def _make_wav(self):
        if os.path.exists(self.wav):
            return
        rate = 22050
        with wave.open(self.wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            frames = bytearray()
            ph = 0.0
            for i in range(int(rate * self.ON_S)):
                t = i / rate
                f = 750 + 450 * (0.5 + 0.5 * math.sin(2 * math.pi * 1.4 * t))
                ph += 2 * math.pi * f / rate
                frames += struct.pack("<h", int(math.copysign(1, math.sin(ph)) * 0.55 * 32000 * 0.9 + math.sin(ph) * 0.1 * 32000))
            w.writeframes(bytes(frames))

    def start(self):
        if self.active:
            return
        self.active = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="siren")
        self._thread.start()

    def stop(self):
        self.active = False
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
        self.sounding = False

    def _run(self):
        if not self.sim:
            self._make_wav()
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "100%"], capture_output=True)
        while self.active:
            self.sounding = True
            if self.sim:
                log.info("SIREN ON")
                end = time.time() + 0.3
                while self.active and time.time() < end:
                    time.sleep(0.05)
            else:
                try:
                    self._proc = subprocess.Popen(["paplay", self.wav], stderr=subprocess.DEVNULL)
                    while self.active and self._proc.poll() is None:
                        time.sleep(0.1)
                except Exception:
                    time.sleep(self.ON_S)
            self.sounding = False
            if not self.active:
                break
            if self.on_gap:
                self.on_gap()
            end = time.time() + (0.4 if self.sim else self.OFF_S)
            while self.active and time.time() < end:
                time.sleep(0.05)
        self.sounding = False


class SecurityManager:
    def __init__(self, cfg, net, simulate=False):
        self.cfg, self.net, self.sim = cfg, net, simulate
        os.makedirs(cfg.SECURITY_DIR, exist_ok=True)
        self.log_path = os.path.join(cfg.SECURITY_DIR, "log.jsonl")
        self.enabled = bool(state_load(cfg).get("security_on", False))
        self.telegram = Telegram(cfg)
        self.siren = Siren(cfg, simulate)
        self.last_capture = {}
        self.sent = []                       # (kind, text) - records what would be sent (for tests / sim)
        self._lock = threading.Lock()
        threading.Thread(target=self._flush_loop, daemon=True, name="sec-flush").start()

    def set_enabled(self, on):
        self.enabled = on
        state_save(self.cfg, security_on=on)
        if not on:
            self.siren.stop()

    def photo_path(self, label):
        safe = "".join(c if c.isalnum() else "_" for c in (label or "Unknown"))
        return os.path.join(self.cfg.SECURITY_DIR, "SEC_%s_%s.jpg" % (time.strftime("%Y%m%d_%H%M%S"), safe))

    def photos(self):
        try:
            fs = [os.path.join(self.cfg.SECURITY_DIR, f) for f in os.listdir(self.cfg.SECURITY_DIR) if f.lower().endswith(".jpg")]
        except OSError:
            return []
        return sorted(fs, key=os.path.getmtime, reverse=True)

    def due(self, key):
        now = time.time()
        if now - self.last_capture.get(key, 0) < self.cfg.SECURITY_COOLDOWN_S:
            return False
        self.last_capture[key] = now
        return True

    def record(self, path, label, kind):
        """Log a security photo; send it to Telegram now (online) or later (queued)."""
        entry = dict(file=os.path.basename(path), name=label, kind=kind, time=time.strftime("%Y-%m-%d %H:%M:%S"), sent=False,
                     siren="ON" if self.siren.active else "off")
        with self._lock:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        threading.Thread(target=self._flush, daemon=True).start()

    def notify_text(self, text):
        self.sent.append(("text", text))
        if self.net.online and self.telegram.configured():
            threading.Thread(target=self.telegram.send_text, args=(text,), daemon=True).start()

    def _entries(self):
        try:
            with open(self.log_path) as f:
                return [json.loads(l) for l in f if l.strip()]
        except Exception:
            return []

    def _flush(self):
        with self._lock:
            entries = self._entries()
            changed = False
            for e in entries:
                if e.get("sent") or not (self.net.online and self.telegram.configured()):
                    continue
                p = os.path.join(self.cfg.SECURITY_DIR, e["file"])
                if not os.path.exists(p):
                    e["sent"] = True
                    continue
                cap = "\U0001F6A8 %s: %s\nDate: %s\nTime: %s\nSiren: %s" % ("INTRUSION - unknown person" if e["kind"] == "unknown" else "Visitor", e["name"] or "Unknown",
                                                                  e["time"][:10], e["time"][11:], e.get("siren", "off"))
                ok, _ = self.telegram.send_photo(p, cap)
                if ok:
                    e["sent"] = True
                    changed = True
                    self.sent.append(("photo", cap))
            if changed:
                with open(self.log_path, "w") as f:
                    for e in entries:
                        f.write(json.dumps(e) + "\n")

    def _flush_loop(self):
        while True:
            time.sleep(30)
            try:
                self._flush()
            except Exception as e:
                log.info("flush error: %s", e)

    def pending(self):
        return sum(1 for e in self._entries() if not e.get("sent"))
