# Luna v2 - desk assistant pet robot (Raspberry Pi 4)

This is your `desk_buddy` project plus six additions. Everything from v1 still works.

| # | Addition | Files |
|---|----------|-------|
| 1 | Hidden-gallery crash fix + secure vault (PBKDF2 PIN or password) | `buddy/vault.py`, patches in `app.py`, `mediaapps.py`, `util.py` |
| 2 | USB pen-drive monitor, status icon, universal explorer, safe eject | `buddy/usbmon.py`, `buddy/textview.py`, patches in `files.py`, `fileapps.py`, `screens.py`, `media.py` |
| 3 | Calendar, 09:00 day-prior reminders, birthday wishes by face | `buddy/calendar_mgr.py` |
| 4 | ESP32 + MG90 servo switch firmware and voice control | `firmware/esp32_switch/esp32_switch.ino`, `buddy/brain.py` |
| 5 | Control Center app (nodes, servo count, switchboard) | `buddy/control_center.py` |
| 6 | Telegram bot (gallery ingest, alarm, telemetry, alerts) | `buddy/telegram_bot.py`, patch in `security.py` |

## Install over an existing Luna
```bash
# Run from the project directory.
bash scripts/install.sh                               # adds avahi (mDNS), requests, zeroconf, pyudev
sudo reboot
```
New settings live at the end of `config.py` (override them in `config_local.py`).

## Tests (run on any PC or on the Pi, no hardware needed)
```bash
python3 tests/test_logic.py        # vault lockout, calendar, ESP32 REST client, Telegram parser (10 tests)
python3 tests/test_ui_smoke.py     # new screens drawn/tapped with a stub pygame (6 tests)
python3 tests/test_app_flow.py     # real App class: old crash is gone, voice -> switch, birthday, Telegram (7 tests)
```
`docs/CHANGES_v1_to_v2.diff` is the full unified diff against your original zip.

## ESP32 quick test
```bash
./venv/bin/python tools/test_esp32.py esp32-switch.local 0 on
```
