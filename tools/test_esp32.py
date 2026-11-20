#!/usr/bin/env python3
"""Talk to an ESP32 switch node from the command line (no Luna needed).
   ./venv/bin/python tools/test_esp32.py esp32-switch.local            -> info + status
   ./venv/bin/python tools/test_esp32.py esp32-switch.local 0 on        -> flick servo 0 ON
   ./venv/bin/python tools/test_esp32.py esp32-switch.local 0 off 60    -> flick OFF with a 60 degree push
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config as cfg
from buddy.control_center import Esp32Api

host = sys.argv[1] if len(sys.argv) > 1 else cfg.ESP32_MDNS_NAME
api = Esp32Api(cfg)
node = dict(id="cli", host=host, port=80)
print("resolve :", api.resolve(host))
print("info    :", api.info(node))
print("status  :", api.status(node))
if len(sys.argv) >= 4:
    angle = int(sys.argv[4]) if len(sys.argv) > 4 else None
    print("servo   :", api.servo(node, int(sys.argv[2]), sys.argv[3], angle))
