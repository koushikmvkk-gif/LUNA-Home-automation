#!/usr/bin/env bash
# Started automatically after the desktop loads (see enable_autostart.sh)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
sleep "${BUDDY_START_DELAY:-6}"          # let audio, Bluetooth and the display settle
exec ./venv/bin/python main.py >> logs/stdout.log 2>&1
