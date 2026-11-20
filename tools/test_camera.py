#!/usr/bin/env python3
"""Webcam + face-recognition test: prints who Luna can see (Ctrl+C to stop) and saves test_frame.jpg."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config as cfg
from buddy.camera import CameraService
from buddy.people import PeopleStore, rank_label
from buddy.util import setup_logging

setup_logging(cfg.LOG_DIR)
people = PeopleStore(cfg)
cam = CameraService(cfg, people)
cam.start()
time.sleep(4)
print("camera:", cam.status, "| face recognition:", cam.recognition)
if cam.capture_jpeg(os.path.join(cfg.BASE_DIR, "test_frame.jpg")):
    print("saved test_frame.jpg - open it to check the picture")
print("Known people:", ", ".join("%s (%s)" % (p["name"], rank_label(people.rank(p))) for p in people.people) or "none yet")
try:
    while True:
        vis = cam.visible(1.5)
        print("  ".join("%s [%s] %.2f" % (d["name"], rank_label(d["rank"]) if d["person"] else "unknown", d["score"]) for d in vis) or "(no face)")
        time.sleep(1)
except KeyboardInterrupt:
    pass
