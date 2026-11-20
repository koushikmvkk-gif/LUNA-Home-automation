"""
Sensor hub: DHT22 (temp/humidity), MQ-2 (gas / air quality),
optional BMP280 (pressure) + ADS1115 (MQ-2 analog) and an online pressure fallback.
Everything degrades gracefully: a missing sensor just shows "--".
"""
import json
import logging
import math
import os
import random
import threading
import time
import urllib.request

from .util import clamp

log = logging.getLogger("sensors")
AQ_LABELS = ["Good", "Moderate", "Poor", "Hazardous"]


def comfort_label(t, h):
    if t is None or h is None:
        return "No data"
    if t >= 33:
        return "Too hot"
    if t >= 29:
        return "Warm"
    if t <= 16:
        return "Cold"
    if h >= 75:
        return "Humid"
    if h <= 30:
        return "Dry"
    return "Comfortable"


class SensorHub(threading.Thread):
    def __init__(self, cfg, simulate=False, net=None):
        super().__init__(daemon=True, name="sensors")
        self.cfg = cfg
        self.sim = simulate
        self.net = net
        self._lock = threading.Lock()
        self._t0 = time.time()
        self._gas_hits = 0
        self._gas_v = None
        self._gas_do = False
        self._last_dht_ok = 0
        self._last_press = 0
        self.sim_gas = False
        self.dht = self.do_pin = self.bmp = self.i2c = None
        self.clean_v = cfg.MQ2_CLEAN_V
        self._load_calibration()
        self.d = dict(temperature=None, humidity=None, pressure=None, pressure_src=None,
                      gas_alert=False, gas_voltage=None, aq_label="Warming up",
                      aq_level=-1, aq_pct=0, comfort="No data", dht_ok=False,
                      has_analog=False, has_bmp=False)
        if not simulate:
            self._init_hw()

    # ------------------------------------------------------------ setup
    def _load_calibration(self):
        path = os.path.join(self.cfg.DATA_DIR, "calibration.json")
        try:
            with open(path) as f:
                self.clean_v = float(json.load(f)["mq2_clean_v"])
                log.info("MQ-2 calibration loaded: clean air = %.3f V", self.clean_v)
        except Exception:
            pass

    def _init_hw(self):
        c = self.cfg
        try:
            import board
            import adafruit_dht
            pin = getattr(board, "D%d" % c.DHT_GPIO)
            try:
                self.dht = adafruit_dht.DHT22(pin, use_pulseio=False)
            except TypeError:
                self.dht = adafruit_dht.DHT22(pin)
            log.info("DHT22 ready on GPIO%d", c.DHT_GPIO)
        except Exception as e:
            log.warning("DHT22 unavailable: %s", e)
        try:
            from gpiozero import DigitalInputDevice
            self.do_pin = DigitalInputDevice(c.MQ2_DO_GPIO, pull_up=None,
                                             active_state=not c.MQ2_DO_ACTIVE_LOW)
            log.info("MQ-2 digital pin ready on GPIO%d", c.MQ2_DO_GPIO)
        except Exception as e:
            log.warning("MQ-2 digital input unavailable: %s", e)
        try:
            import smbus2
            self.i2c = smbus2.SMBus(c.I2C_BUS)
        except Exception as e:
            log.info("I2C not available (optional): %s", e)
        if self.i2c and c.ADS1115_ENABLED:
            try:
                self._ads_read()
                self.d["has_analog"] = True
                log.info("ADS1115 found at 0x%02X", c.ADS1115_ADDR)
            except Exception:
                log.info("ADS1115 not found - using MQ-2 digital output only")
        if c.BMP280_ENABLED:
            try:
                import board
                import busio
                import adafruit_bmp280
                i2c = busio.I2C(board.SCL, board.SDA)
                for addr in c.BMP280_ADDRS:
                    try:
                        self.bmp = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=addr)
                        self.d["has_bmp"] = True
                        log.info("BMP280 found at 0x%02X", addr)
                        break
                    except Exception:
                        continue
            except Exception as e:
                log.info("BMP280 not available (optional): %s", e)

    # ---------------------------------------------------------- readers
    def _ads_read(self):
        """Single-shot read of ADS1115 AIN0 (+/-4.096 V range) -> volts at the ADC pin."""
        addr = self.cfg.ADS1115_ADDR
        self.i2c.write_i2c_block_data(addr, 0x01, [0xC3, 0x83])
        time.sleep(0.015)
        hi, lo = self.i2c.read_i2c_block_data(addr, 0x00, 2)
        raw = (hi << 8) | lo
        if raw & 0x8000:
            raw -= 65536
        return raw * 4.096 / 32768.0

    def _read_dht(self):
        if self.sim:
            t = time.time()
            return (27.5 + 2.0 * math.sin(t / 90.0) + random.uniform(-0.1, 0.1),
                    55 + 6.0 * math.sin(t / 130.0) + random.uniform(-0.3, 0.3))
        if not self.dht:
            return None
        try:
            t, h = self.dht.temperature, self.dht.humidity
            if t is not None and h is not None and -20 < t < 80 and 0 <= h <= 100:
                return t, h
        except RuntimeError:
            pass                       # normal DHT checksum / timing hiccup
        except Exception as e:
            log.warning("DHT22 error: %s - re-initialising", e)
            try:
                self.dht.exit()
            except Exception:
                pass
            self._init_hw()
        return None

    def _read_gas(self):
        if self.sim:
            return self.sim_gas, (0.6 + (2.4 if self.sim_gas else random.uniform(-0.03, 0.03)))
        active = bool(self.do_pin.is_active) if self.do_pin else False
        volts = None
        if self.d["has_analog"]:
            try:
                volts = self._ads_read() * self.cfg.MQ2_DIVIDER_RATIO
            except Exception:
                volts = None
        return active, volts

    def _fetch_pressure_online(self):
        url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
               "&current=surface_pressure" % (self.cfg.LATITUDE, self.cfg.LONGITUDE))
        try:
            with urllib.request.urlopen(url, timeout=6) as r:
                return float(json.load(r)["current"]["surface_pressure"])
        except Exception as e:
            log.info("online pressure fetch failed: %s", e)
            return None

    # ------------------------------------------------------------- loop
    def run(self):
        cfg = self.cfg
        last_dht = 0
        while True:
            now = time.time()
            upd = {}
            # --- gas (fast loop, 0.5 s)
            try:
                active, volts = self._read_gas()
                self._gas_hits = self._gas_hits + 1 if active else 0
                upd.update(self._eval_air(now, volts))
            except Exception as e:
                log.warning("gas read error: %s", e)
            # --- DHT22 (every 2.5 s)
            if now - last_dht >= 2.5:
                last_dht = now
                r = self._read_dht()
                if r:
                    upd["temperature"], upd["humidity"] = round(r[0], 1), round(r[1], 1)
                    self._last_dht_ok = now
                upd["dht_ok"] = (now - self._last_dht_ok) < 20
            # --- pressure
            if now - self._last_press >= (5 if self.sim else cfg.PRESSURE_REFRESH_S) \
                    or self.d["pressure"] is None and now - self._last_press > 20:
                self._last_press = now
                p, src = None, None
                if self.sim:
                    p, src = 913.0 + 1.5 * math.sin(now / 600.0), "sim"
                elif self.bmp:
                    try:
                        p, src = float(self.bmp.pressure), "sensor"
                    except Exception:
                        pass
                elif self.net is not None and self.net.online:
                    p = self._fetch_pressure_online()
                    src = "online" if p else None
                if p:
                    upd["pressure"], upd["pressure_src"] = round(p, 1), src
            with self._lock:
                self.d.update(upd)
                self.d["comfort"] = comfort_label(self.d["temperature"], self.d["humidity"])
            time.sleep(0.5)

    def _eval_air(self, now, volts):
        cfg = self.cfg
        if now - self._t0 < cfg.MQ2_WARMUP_S and not self.sim:
            return dict(gas_alert=False, aq_label="Warming up", aq_level=-1,
                        aq_pct=0, gas_voltage=volts)
        do_hit = self._gas_hits >= cfg.GAS_CONFIRM_READS
        level, pct = 0, 0
        if volts is not None:
            ratio = volts / max(self.clean_v, 0.05)
            pct = clamp((ratio - 1.0) / (cfg.AQ_RATIOS[2] * 1.4 - 1.0) * 100, 0, 100)
            level = sum(ratio >= th for th in cfg.AQ_RATIOS)
        if do_hit:
            level, pct = 3, max(pct, 90)
        label = AQ_LABELS[level]
        if volts is None and do_hit:
            label = "Gas detected"
        return dict(gas_alert=(level >= 3), aq_label=label, aq_level=level,
                    aq_pct=round(pct), gas_voltage=volts)

    def snapshot(self):
        with self._lock:
            return dict(self.d)
