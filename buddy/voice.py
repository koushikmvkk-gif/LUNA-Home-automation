"""
Offline speech recognition with Vosk + a USB microphone.
`ConsoleListener` replaces it in simulation mode (type commands in the terminal).
"""
import json
import logging
import os
import queue
import threading
import time

log = logging.getLogger("voice")


class ConsoleListener(threading.Thread):
    available = True
    status = "console"

    def __init__(self, on_text, on_partial=None, **kw):
        super().__init__(daemon=True, name="console-listener")
        self.on_text = on_text
        self.paused = False

    def run(self):
        import sys
        while True:
            line = sys.stdin.readline()
            if not line:
                return
            self.on_text(line.strip())


class Listener(threading.Thread):
    def __init__(self, cfg, on_text, on_partial=None, is_paused=lambda: False):
        super().__init__(daemon=True, name="listener")
        self.cfg, self.on_text, self.on_partial, self.is_paused = cfg, on_text, on_partial, is_paused
        self.available = False
        self.status = "starting"
        self.q = queue.Queue(maxsize=60)

    # -------------------------------------------------------------- stream
    def _candidates(self, sd):
        c = self.cfg
        out = []
        if c.MIC_DEVICE is not None:
            out.append((c.MIC_DEVICE, 16000, 1))
        else:
            out.append((None, 16000, 1))              # PulseAudio/PipeWire default source
        try:
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0 and c.MIC_NAME_HINT.lower() in d["name"].lower():
                    rate = int(d["default_samplerate"])
                    out += [(i, 16000, 1), (i, rate, 1), (i, rate, 2)]
        except Exception:
            pass
        return out

    def _open(self):
        import sounddevice as sd
        last = None
        for dev, rate, ch in self._candidates(sd):
            try:
                sd.check_input_settings(device=dev, samplerate=rate, channels=ch)
                self._rate, self._ch = rate, ch

                def cb(indata, frames, t, status):
                    try:
                        self.q.put_nowait(bytes(indata))
                    except queue.Full:
                        pass

                stream = sd.RawInputStream(samplerate=rate, blocksize=int(rate * 0.25), device=dev,
                                           dtype="int16", channels=ch, callback=cb)
                stream.start()
                log.info("microphone opened: device=%s rate=%d ch=%d", dev, rate, ch)
                return stream
            except Exception as e:
                last = e
        raise RuntimeError("no usable microphone: %s" % last)

    def _to_16k_mono(self, data):
        if self._rate == 16000 and self._ch == 1:
            return data
        import numpy as np
        x = np.frombuffer(data, dtype=np.int16)
        if self._ch > 1:
            x = x.reshape(-1, self._ch)[:, 0]
        if self._rate != 16000:
            if self._rate % 16000 == 0:
                f = self._rate // 16000
                x = x[: len(x) // f * f].reshape(-1, f).mean(axis=1)
            else:
                x = x[(np.arange(0, len(x), self._rate / 16000.0)).astype(int)]
        return x.astype(np.int16).tobytes()

    # ----------------------------------------------------------------- run
    def run(self):
        if not os.path.isdir(self.cfg.VOSK_MODEL_DIR):
            self.status = "no voice model"
            log.error("Vosk model not found at %s - run scripts/download_vosk_model.sh",
                      self.cfg.VOSK_MODEL_DIR)
            return
        try:
            import vosk
            vosk.SetLogLevel(-1)
            model = vosk.Model(self.cfg.VOSK_MODEL_DIR)
            rec = vosk.KaldiRecognizer(model, 16000)
        except Exception as e:
            self.status = "vosk error"
            log.error("cannot start Vosk: %s", e)
            return
        while True:                                   # keep retrying if the mic is unplugged
            try:
                stream = self._open()
            except Exception as e:
                self.status = "no microphone"
                log.warning("%s - retrying in 5 s", e)
                time.sleep(5)
                continue
            self.available, self.status = True, "listening"
            was_paused, last_partial = False, ""
            try:
                while True:
                    data = self.q.get(timeout=3)
                    if self.is_paused():
                        was_paused = True
                        continue
                    if was_paused:
                        rec.Reset()
                        was_paused = False
                    data = self._to_16k_mono(data)
                    if rec.AcceptWaveform(data):
                        text = json.loads(rec.Result()).get("text", "").strip()
                        last_partial = ""
                        if text:
                            log.info("heard: %s", text)
                            self.on_text(text)
                    elif self.on_partial:
                        p = json.loads(rec.PartialResult()).get("partial", "")
                        if p and p != last_partial:
                            last_partial = p
                            self.on_partial(p)
            except queue.Empty:
                log.warning("no audio from microphone - reopening")
            except Exception as e:
                log.warning("listener error: %s", e)
            finally:
                self.available, self.status = False, "no microphone"
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
