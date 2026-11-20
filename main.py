#!/usr/bin/env python3
"""Luna - friendly desk assistant pet robot.

    python3 main.py          run on the Raspberry Pi (full screen)
    python3 main.py --sim    run on any PC with fake sensors (type commands in the terminal)
"""
import argparse
import fcntl
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg                      # noqa: E402
from buddy.util import setup_logging      # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true", help="simulate sensors/audio (for testing on a PC)")
    ap.add_argument("--window", action="store_true", help="run in a window instead of full screen")
    args = ap.parse_args()
    if args.window or args.sim:
        cfg.FULLSCREEN = False
    setup_logging(cfg.LOG_DIR)

    lock = open("/tmp/desk_buddy.lock", "w")       # only one copy may run
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Luna is already running.")
        return 0

    from buddy.app import App
    App(cfg, simulate=args.sim).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
