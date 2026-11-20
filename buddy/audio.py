"""
Audio routing + text-to-speech.

* AudioRouter picks the output automatically: Bluetooth speaker if connected,
  else a USB speaker, else the default output. It also selects the USB mic.
* BluetoothKeeper keeps trying to (re)connect the paired speaker.
* Speaker speaks with the Google voice when online, otherwise offline espeak-ng.
"""
import hashlib
import logging
import os
import queue
import subprocess
import tempfile
import threading
import time

log = logging.getLogger("audio")


def sh(cmd, timeout=6):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout
    except Exception:
        return 1, ""


class AudioRouter:
    def __init__(self, cfg):
        self.cfg = cfg
        self.label = "No audio"
        self._sink = None
        self._vol_applied = None
        self.volume = cfg.DEFAULT_VOLUME

    def _names(self, kind):
        rc, out = sh(["pactl", "list", "short", kind])
        names = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                names.append(parts[1])
        return names

    def refresh(self):
        sinks = self._names("sinks")
        bt = [s for s in sinks if s.startswith("bluez")]
        usb = [s for s in sinks if "usb" in s.lower()]
        choice, label = None, "Default audio"
        for kind in self.cfg.AUDIO_PRIORITY:
            if kind == "bluetooth" and bt:
                choice, label = bt[0], "BT speaker"
                break
            if kind == "usb" and usb:
                choice, label = usb[0], "USB speaker"
                break
        self.label = label
        if choice and choice != self._sink:
            sh(["pactl", "set-default-sink", choice])
            log.info("audio output -> %s (%s)", label, choice)
            self._sink = choice
            self._vol_applied = None
        sources = [s for s in self._names("sources")
                   if not s.endswith(".monitor") and "usb" in s.lower()]
        if sources:
            sh(["pactl", "set-default-source", sources[0]])
        if self._vol_applied != self.volume:
            sh(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "%d%%" % self.volume])
            self._vol_applied = self.volume

    def change_volume(self, delta):
        self.volume = max(20, min(100, self.volume + delta))
        return self.volume


class BluetoothKeeper(threading.Thread):
    """Keeps the chosen Bluetooth speaker connected (MAC from data/bt_speaker.json or config)."""

    def __init__(self, cfg):
        super().__init__(daemon=True, name="bt")
        self.cfg = cfg
        self.connected = False
        self.paused = False
        self.file = os.path.join(cfg.DATA_DIR, "bt_speaker.json")

    def mac(self):
        try:
            import json
            with open(self.file) as f:
                return json.load(f).get("mac") or self.cfg.BT_SPEAKER_MAC
        except Exception:
            return self.cfg.BT_SPEAKER_MAC

    def remember(self, mac):
        import json
        with open(self.file, "w") as f:
            json.dump({"mac": mac}, f)
        self.paused = False

    def run(self):
        sh(["bluetoothctl", "power", "on"])
        while True:
            mac = self.mac()
            if mac and not self.paused:
                rc, out = sh(["bluetoothctl", "info", mac])
                self.connected = "Connected: yes" in out
                if not self.connected:
                    log.info("trying to connect Bluetooth speaker %s", mac)
                    sh(["bluetoothctl", "connect", mac], timeout=20)
            time.sleep(self.cfg.BT_RETRY_S)


class Speaker(threading.Thread):
    def __init__(self, cfg, router, net, simulate=False):
        super().__init__(daemon=True, name="speaker")
        self.cfg, self.router, self.net, self.sim = cfg, router, net, simulate
        self.q = queue.Queue()
        self.speaking = False
        self.quiet_until = 0.0
        self.mode = "offline"
        self.cache_dir = os.path.join(cfg.DATA_DIR, "tts_cache")
        os.makedirs(self.cache_dir, exist_ok=True)

    def say(self, text):
        if text:
            self.q.put(text)

    def busy(self):
        return self.speaking or not self.q.empty()

    def stop_now(self):
        """Interrupt whatever is being spoken right now (and drop the queue)."""
        self.clear()
        p = getattr(self, "_cur", None)
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

    def _run(self, cmd, timeout=60):
        try:
            self._cur = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return self._cur.wait(timeout)
        except Exception:
            return 1

    def clear(self):
        try:
            while True:
                self.q.get_nowait()
        except queue.Empty:
            pass

    def run(self):
        while True:
            text = self.q.get()
            self.speaking = True
            try:
                if self.sim:
                    log.info("SAY: %s", text)
                    time.sleep(0.06 * len(text) + 0.3)
                else:
                    self.router.refresh()
                    self._speak(text)
            except Exception as e:
                log.warning("speech failed: %s", e)
            finally:
                self.speaking = False
                self.quiet_until = time.time() + 0.6

    def shutter(self):
        """Camera click sound."""
        if self.sim:
            log.info("*click*")
            return
        import math as _m
        import struct
        import wave
        path = os.path.join(self.cache_dir, "shutter.wav")
        if not os.path.exists(path):
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(22050)
                frames = b""
                for i in range(int(22050 * 0.14)):
                    env = _m.exp(-i / 700.0)
                    v = (_m.sin(i * 0.9) * 0.5 + (((i * 7919) % 200) / 100.0 - 1) * 0.5) * env
                    frames += struct.pack("<h", int(v * 20000))
                w.writeframes(frames)
        threading.Thread(target=self._play_wav, args=(path,), daemon=True).start()

    # -------------------------------------------------------------- engines
    def _speak(self, text):
        if self.cfg.ONLINE_VOICE and self.net.online:
            mp3 = self._gtts(text)
            if mp3 and self._play_mp3(mp3):
                self.mode = "online"
                return
        self.mode = "offline"
        wav = os.path.join(tempfile.gettempdir(), "buddy_tts.wav")
        sh(["espeak-ng", "-v", self.cfg.ESPEAK_VOICE, "-s", str(self.cfg.ESPEAK_SPEED),
            "-p", str(self.cfg.ESPEAK_PITCH), "-w", wav, text], timeout=15)
        self._play_wav(wav)

    def _gtts(self, text):
        path = os.path.join(self.cache_dir, hashlib.sha1(text.encode()).hexdigest() + ".mp3")
        if os.path.exists(path):
            return path
        try:
            from gtts import gTTS
            try:
                t = gTTS(text, lang=self.cfg.GTTS_LANG, tld=self.cfg.GTTS_TLD, timeout=8)
            except TypeError:
                t = gTTS(text, lang=self.cfg.GTTS_LANG, tld=self.cfg.GTTS_TLD)
            t.save(path)
            return path
        except Exception as e:
            log.info("online voice failed, using offline voice: %s", e)
            return None

    def _play_mp3(self, path):
        for cmd in (["mpg123", "-q", path], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path]):
            rc = self._run(cmd)
            if rc == 0 or rc < 0:
                return True
        return False

    def _play_wav(self, path):
        rc = self._run(["paplay", path])
        if rc not in (0,) and rc >= 0:
            self._run(["aplay", "-q", path])
