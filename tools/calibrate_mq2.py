#!/usr/bin/env python3
"""
MQ-2 calibration (run in CLEAN, ventilated air after the sensor has warmed up).
* With an ADS1115 fitted: measures the clean-air voltage for 3 minutes and saves it.
* Without ADS1115: shows the live DO state so you can turn the blue trimmer on the MQ-2 module
  until the DO LED just switches OFF in clean air.
"""
import json, os, statistics, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config as cfg
from buddy.sensors import SensorHub

cfg.MQ2_WARMUP_S = 0
hub = SensorHub(cfg)
print("MQ-2 calibration. Keep the sensor in clean air. Pre-heat it for at least 3 minutes first.")
if not hub.d["has_analog"]:
    print("No ADS1115 found -> digital mode. Turn the trimmer until DO reads CLEAN. Ctrl+C to stop.")
    try:
        while True:
            print("DO:", "GAS!" if (hub.do_pin and hub.do_pin.is_active) else "clean"); time.sleep(1)
    except KeyboardInterrupt:
        sys.exit(0)
print("Pre-heating 120 s ...")
time.sleep(120)
vals = []
for i in range(180):
    v = hub._ads_read() * cfg.MQ2_DIVIDER_RATIO
    vals.append(v)
    if i % 10 == 0:
        print("  %3ds  %.3f V" % (i, v))
    time.sleep(1)
clean = statistics.median(vals)
os.makedirs(cfg.DATA_DIR, exist_ok=True)
with open(os.path.join(cfg.DATA_DIR, "calibration.json"), "w") as f:
    json.dump({"mq2_clean_v": round(clean, 3)}, f)
print("\nSaved clean-air voltage = %.3f V to data/calibration.json" % clean)
