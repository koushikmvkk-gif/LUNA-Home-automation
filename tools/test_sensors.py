#!/usr/bin/env python3
"""Live sensor test: shows DHT22, MQ-2, touch pad, and optional BMP280/ADS1115. Ctrl+C to stop."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config as cfg
from buddy.sensors import SensorHub
from buddy.touch import TouchPad
from buddy.util import NetMonitor, setup_logging

setup_logging(cfg.LOG_DIR)
cfg.MQ2_WARMUP_S = 0
net = NetMonitor(); net.start()
hub = SensorHub(cfg, net=net); hub.start()
touch = TouchPad(cfg)
print("Touch the TTP223 pad to test it. Ctrl+C to quit.\n")
try:
    while True:
        for ev in touch.poll():
            print("   >>> TOUCH EVENT:", ev)
        s = hub.snapshot()
        print("T=%s C  H=%s %%  P=%s hPa (%s)  Air=%s  gasV=%s  alert=%s  dht_ok=%s" % (
            s["temperature"], s["humidity"], s["pressure"], s["pressure_src"], s["aq_label"],
            None if s["gas_voltage"] is None else round(s["gas_voltage"], 2), s["gas_alert"], s["dht_ok"]))
        time.sleep(1)
except KeyboardInterrupt:
    pass
