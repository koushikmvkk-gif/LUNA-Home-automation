"""Bidirectional Telegram bot for Luna (direct HTTPS long-polling with `requests` - no extra library).

Uses the BOT_TOKEN / CHAT_ID you already typed in Settings > Security > Telegram alerts (data/telegram.json).
ONLY messages from that chat id are obeyed - everybody else is silently ignored (and logged).

Receives
    photo / video / image or video document   -> saved to data/gallery/ + toast "New media added to Gallery via Telegram"
    /arm_alarm  /disarm_alarm  /alarm_status   -> guard mode on / off / report
    /room_status                               -> temperature, humidity (DHT22), air quality (MQ-2), pressure (BMP280)
    /snapshot                                  -> webcam picture sent back to you
    /help
Sends
    gas / smoke alert (rate limited, repeated every GAS_ALERT_REPEAT_S while it lasts, plus an all-clear)
    intrusion snapshot with date, time and siren status (done by security.py - see caption there)
"""
import logging
import os
import re
import threading
import time

log = logging.getLogger("tgbot")

HELP = ("Luna commands:\n/arm_alarm - guard mode ON\n/disarm_alarm - back to pet mode\n/alarm_status - guard + siren state\n"
        "/room_status - temperature, humidity, air quality, pressure\n/snapshot - live webcam picture\n"
        "Send me a photo or video and I will put it in Luna's gallery.")


class TelegramBot(threading.Thread):
    def __init__(self, app):
        super().__init__(daemon=True, name="tgbot")
        self.app = app
        self.cfg = app.cfg
        self.running = True
        self.offset = 0
        self.gas_active = False
        self.gas_last = 0.0
        self._cmds_set = False
        self.sent = []                              # (kind, text) - for the simulator / tests

    # ----------------------------------------------------------------- plumbing
    @property
    def tg(self):
        return self.app.sec.telegram

    def ready(self):
        return self.cfg.TELEGRAM_BOT_ENABLED and self.tg.configured() and (self.app.net.online or self.app.sim)

    def _api(self, method, data=None, files=None, timeout=15):
        import requests
        r = requests.post("https://api.telegram.org/bot%s/%s" % (self.tg.token, method), data=data, files=files, timeout=timeout)
        return r

    def say(self, text):
        """Send a text to the configured chat (never raises)."""
        self.sent.append(("text", text))
        if self.app.sim or not self.tg.configured():
            return False
        try:
            return self._api("sendMessage", {"chat_id": self.tg.chat_id, "text": text}).ok
        except Exception as e:
            log.info("send failed: %s", e)
            return False

    def send_photo(self, path, caption):
        self.sent.append(("photo", caption))
        if self.app.sim or not self.tg.configured():
            return False
        try:
            with open(path, "rb") as f:
                return self._api("sendPhoto", {"chat_id": self.tg.chat_id, "caption": caption}, {"photo": f}, 30).ok
        except Exception as e:
            log.info("photo failed: %s", e)
            return False

    def stop(self):
        self.running = False

    # ----------------------------------------------------------------- main loop
    def run(self):
        backoff = 3
        while self.running:
            if not self.ready() or self.app.sim:
                time.sleep(4)
                continue
            try:
                if not self._cmds_set:
                    self._set_commands()
                self.poll_once()
                backoff = 3
            except Exception as e:
                log.info("telegram poll error: %s", e)
                time.sleep(backoff)
                backoff = min(60, backoff * 2)

    def _set_commands(self):
        import json
        cmds = [("arm_alarm", "Guard mode ON"), ("disarm_alarm", "Guard mode OFF"), ("alarm_status", "Alarm status"),
                ("room_status", "Temperature, humidity, air"), ("snapshot", "Webcam picture"), ("help", "List commands")]
        self._api("setMyCommands", {"commands": json.dumps([{"command": c, "description": d} for c, d in cmds])})
        self._cmds_set = True

    def poll_once(self):
        r = self._api("getUpdates", {"offset": self.offset, "timeout": self.cfg.TELEGRAM_POLL_TIMEOUT_S, "allowed_updates": '["message"]'},
                      timeout=self.cfg.TELEGRAM_POLL_TIMEOUT_S + 10)
        if not r.ok:
            raise RuntimeError("getUpdates %s" % r.status_code)
        for upd in r.json().get("result", []):
            self.offset = upd["update_id"] + 1
            try:
                self.handle(upd.get("message") or {})
            except Exception:
                log.exception("telegram update failed")

    # ----------------------------------------------------------------- one incoming message
    def handle(self, msg):
        if not msg:
            return
        chat = str(msg.get("chat", {}).get("id", ""))
        if chat != str(self.tg.chat_id):
            log.warning("telegram: ignored message from unauthorised chat %s", chat)
            return
        text = (msg.get("text") or "").strip()
        if text.startswith("/"):
            self.command(text)
            return
        media = self._media_of(msg)
        if media:
            self.download_media(*media)

    def command(self, text):
        cmd = re.match(r"/(\w+)", text).group(1).lower()
        a = self.app
        if cmd in ("start", "help"):
            self.say(HELP)
        elif cmd == "arm_alarm":
            a.events.put(("call", (lambda _: a.set_security(True, "Telegram"), None)))
            self.say("Guard mode ARMED. Luna is watching the room.")
        elif cmd == "disarm_alarm":
            a.events.put(("call", (lambda _: a.set_security(False, "Telegram"), None)))
            self.say("Guard mode DISARMED. Luna is back in pet mode.")
        elif cmd == "alarm_status":
            self.say(self.alarm_status())
        elif cmd == "room_status":
            self.say(self.room_status())
        elif cmd == "snapshot":
            threading.Thread(target=self._snapshot, daemon=True).start()
        else:
            self.say("Unknown command. Send /help")

    # ----------------------------------------------------------------- reports
    def alarm_status(self):
        s = self.app.sec
        return "Alarm: %s\nSiren: %s\nIntruder photos waiting to upload: %d\nTime: %s" % (
            "ARMED (guard mode)" if s.enabled else "DISARMED (pet mode)", "SOUNDING" if s.siren.active else "off", s.pending(), time.strftime("%Y-%m-%d %H:%M:%S"))

    def room_status(self):
        d = self.app.sensors.snapshot()
        f = lambda v, fmt: (fmt % v) if v is not None else "--"
        src = d.get("pressure_src") or ("BMP280" if d.get("has_bmp") else "online")
        gas = ("Gas level %d%%" % d["aq_pct"]) if d.get("has_analog") else ("GAS DETECTED" if d.get("gas_alert") else "no gas detected")
        return ("Room status (%s)\nTemperature: %s C\nHumidity: %s %% (DHT22)\nAir quality: %s (MQ-2, %s)\nPressure: %s hPa (%s)\nComfort: %s"
                % (time.strftime("%H:%M:%S"), f(d["temperature"], "%.1f"), f(d["humidity"], "%.0f"), d["aq_label"], gas, f(d["pressure"], "%.0f"), src, d.get("comfort", "--")))

    def _snapshot(self):
        path = os.path.join(self.cfg.DATA_DIR, "tg_snapshot.jpg")
        if self.app.camera.capture_jpeg(path, time.strftime("%Y-%m-%d  %H:%M:%S")):
            self.send_photo(path, "Snapshot %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
        else:
            self.say("Sorry, the webcam did not give me a picture.")

    # ----------------------------------------------------------------- incident alerts
    def gas_tick(self, snap, now=None):
        """Call every frame from the main loop; cheap. Sends the alert + repeats + all-clear."""
        now = now or time.time()
        if snap.get("gas_alert"):
            if not self.gas_active or now - self.gas_last >= self.cfg.GAS_ALERT_REPEAT_S:
                first = not self.gas_active
                self.gas_active, self.gas_last = True, now
                lvl = ("Gas level: %d%%\n" % snap["aq_pct"]) if snap.get("has_analog") else ""
                txt = ("\u26a0\ufe0f ALERT: Gas/Smoke detected!\n%sAir quality: %s\nTemperature: %s C   Humidity: %s %%\nTime: %s%s"
                       % (lvl, snap.get("aq_label"), "%.1f" % snap["temperature"] if snap.get("temperature") is not None else "--",
                          "%.0f" % snap["humidity"] if snap.get("humidity") is not None else "--", time.strftime("%Y-%m-%d %H:%M:%S"),
                          "" if first else "\n(still detected)"))
                threading.Thread(target=self.say, args=(txt,), daemon=True).start()
        elif self.gas_active:
            self.gas_active = False
            threading.Thread(target=self.say, args=("\u2705 Air is clear again (%s)." % time.strftime("%H:%M:%S"),), daemon=True).start()

    # ----------------------------------------------------------------- media ingest
    @staticmethod
    def _media_of(msg):
        """-> (kind, file_id, ext, size) or None."""
        if msg.get("photo"):
            p = max(msg["photo"], key=lambda x: x.get("file_size", 0) or x.get("width", 0))
            return "photo", p["file_id"], ".jpg", p.get("file_size", 0)
        for key in ("video", "video_note", "animation"):
            if msg.get(key):
                v = msg[key]
                return "video", v["file_id"], ".mp4", v.get("file_size", 0)
        d = msg.get("document")
        if d:
            mime = (d.get("mime_type") or "").lower()
            name = (d.get("file_name") or "").lower()
            ext = os.path.splitext(name)[1] or (".jpg" if "jpeg" in mime else ".png" if "png" in mime else ".mp4" if "mp4" in mime else "")
            if mime.startswith("image/") or ext in (".jpg", ".jpeg", ".png", ".webp"):
                return "photo", d["file_id"], ext if ext in (".jpg", ".jpeg", ".png", ".webp") else ".jpg", d.get("file_size", 0)
            if mime.startswith("video/") or ext in (".mp4", ".mkv", ".avi", ".mov", ".webm"):
                return "video", d["file_id"], ext if ext in (".mp4", ".mkv", ".avi", ".mov", ".webm") else ".mp4", d.get("file_size", 0)
        return None

    def download_media(self, kind, file_id, ext, size):
        import requests
        if size and size > self.cfg.TELEGRAM_MAX_FILE_MB * 1024 * 1024:
            self.say("That file is bigger than %d MB - Telegram bots cannot download it. Please send a smaller one." % self.cfg.TELEGRAM_MAX_FILE_MB)
            return None
        r = self._api("getFile", {"file_id": file_id})
        if not r.ok:
            self.say("Telegram would not let me download that file.")
            return None
        fpath = r.json()["result"]["file_path"]
        os.makedirs(self.cfg.GALLERY_DIR, exist_ok=True)
        base = "TG_%s" % time.strftime("%Y%m%d_%H%M%S")
        dest, n = os.path.join(self.cfg.GALLERY_DIR, base + ext), 1
        while os.path.exists(dest):
            dest = os.path.join(self.cfg.GALLERY_DIR, "%s_%d%s" % (base, n, ext))
            n += 1
        part = dest + ".part"
        with requests.get("https://api.telegram.org/file/bot%s/%s" % (self.tg.token, fpath), stream=True, timeout=60) as dl:
            dl.raise_for_status()
            with open(part, "wb") as f:
                for chunk in dl.iter_content(65536):
                    f.write(chunk)
        os.replace(part, dest)                         # the gallery never sees half-written files
        log.info("telegram media saved: %s", dest)
        self.app.events.put(("call", (self.app.on_telegram_media, dest)))
        self.say("\u2705 Saved to Luna's gallery.")
        return dest
