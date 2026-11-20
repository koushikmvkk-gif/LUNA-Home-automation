#!/usr/bin/env python3
"""Checks audio routing (Bluetooth/USB speaker), speaks a sentence and measures the microphone level."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config as cfg
from buddy.audio import AudioRouter, Speaker
from buddy.util import NetMonitor

net = NetMonitor(); print("Internet:", net._check()); net.online = net._check()
router = AudioRouter(cfg); router.refresh()
print("Selected output:", router.label)
sp = Speaker(cfg, router, net); sp.start()
sp.say("Hello! This is a speaker test from Desk Buddy.")
while sp.busy() or True:
    time.sleep(0.5)
    if not sp.busy():
        break
print("Voice engine used:", sp.mode)
try:
    import sounddevice as sd, numpy as np
    print("\nInput devices:")
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            print("  [%d] %s" % (i, d["name"]))
    print("\nSpeak now for 3 seconds...")
    rec = sd.rec(int(3 * 16000), samplerate=16000, channels=1, dtype="int16"); sd.wait()
    level = int(np.abs(rec).mean())
    print("Average mic level:", level, "(should be well above ~50 while you talk)")
except Exception as e:
    print("Microphone test failed:", e)
