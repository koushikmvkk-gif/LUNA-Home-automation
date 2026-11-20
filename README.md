# LUNA Home Automation

Luna is an offline-capable home automation AI and Raspberry Pi 4 desk assistant pet robot (developer: Koushik).

A friendly desk robot with an animated face on a 7" HDMI display. It listens (USB mic), talks
(Bluetooth or USB speaker), reacts to touch (TTP223), watches the room (DHT22, MQ-2, optional BMP280)
and works both **online** and **offline**.

Full step-by-step instructions are in [`Luna_Instruction_Guide.pdf`](Luna_Instruction_Guide.pdf). The v2 additions are documented in [`README_V2.md`](README_V2.md), with the complete build guide in [`docs/Luna_v2_Build_Guide.pdf`](docs/Luna_v2_Build_Guide.pdf).

## Quick start (on the Pi)
```bash
# Run these commands from the project directory.
bash scripts/install.sh            # installs everything + autostart
bash scripts/pair_bluetooth.sh     # pair your speaker once
./venv/bin/python tools/test_sensors.py
sudo reboot                        # Luna now starts by itself
```
Try it on a normal PC first: `python3 main.py --sim` (needs `pip install pygame`; type commands in the terminal,
Space = touch, A = analysis, G = fake gas, Esc = quit).

## Voice (say "Luna ..." first)
room condition / temperature / humidity / air pressure / air quality / time / date / timer for 5 minutes /
tell me a joke / volume up / go to sleep / what can you do.
**No wake word needed:** "switch to Raspberry Pi", "switch to OS", "switch to calibration".

## Touch
tap = happy reaction, double tap = room analysis (10 s), long press = sleep / wake.
Works on the TTP223 pad **and** on the 7" HDMI touch screen (a ripple appears and Luna's eyes follow your finger).

## Ask Luna about herself
"Luna, who are you?" -> "I am Luna, not WALL-E ..."; "Luna, who is Koushik?", "when was Koushik born?", "where does he study?".
Edit the facts in `config.py` (DEVELOPER_*).

Settings live in `config.py`; put your own overrides in `config_local.py`.

## Camera, faces and priorities (new)
* Plug in a USB webcam. Luna recognises faces locally (OpenCV YuNet + SFace) and greets people by name with the time of day ("Good evening, Koushik!").
* Introduce someone: **"Luna, this is Rahul"** (or "Luna, my name is Rahul") - she captures the face and remembers it. The very first person introduced becomes the **master**; everyone after is **least priority**.
* Priority files in `data/priority/`: `1_masters.json` (max 6 people, exactly 10 photos each) | `2_priority.json` (max 10 people, up to 5 photos) | `3_least_priority.json` (unlimited; everyone Luna meets lands here).
  Moving people between levels, renaming and deleting is done by hand in **Settings > Privacy** (PIN protected).
* With several people in view, the **highest-ranking recognised person is treated as the one giving commands**.
* Photos: "Luna, take a selfie / take a picture / take a group photo", "Luna, show the image" (10 s, touch pauses the timer), "Luna, open the gallery", "Luna, open the hidden gallery" (4-digit PIN typed on screen).
* In the gallery Luna shrinks to a corner: long-press her face and drag to move it, double-tap it to go back to robot mode.
* Tools: `tools/test_camera.py`, `tools/manage_people.py`.

## Menu, apps and settings (new)
* Hamburger button above Luna's face -> **Settings, Gallery, Music, Movies, Room Analysis, Camera, Drawing**. Everything can also be opened by voice ("Luna, open music").
* In every app Luna shrinks to a mini face: long-press + drag to move her, double-tap to return to robot mode; the round Back button goes back one screen. She still answers voice and can comment on what is on the screen ("Luna, any suggestion?").
* **Music**: album folders in `data/music/<Album>/` (God, Romantic, Upbeat, Sad, Chill, Motivational, Nostalgic + your own). "Luna, play a god song", "Luna, play the song in the ocean", pause / resume / next / forward 10 seconds / rewind 10 seconds / loop / shuffle.
* **Movies**: videos in `data/movies/`; camera videos live in the Gallery. **Camera**: photo + video. **Drawing**: whiteboard with colours, pens, eraser, save and re-edit.
* **Settings**: Privacy (PIN, default 0223 - change it), About (all voice commands + creator), Wi-Fi, Bluetooth, Display (brightness + volume), Switch to Raspberry Pi OS, Security (guard mode, Telegram alerts, siren for unknown faces).
* Needs `mpv` (installed by `scripts/install.sh`).

## Documents, PDF reader and USB drive (new)
* Menu tiles **Documents** (`data/pdfs/`) and **USB Drive**. Plug a pen drive in and Luna announces it; browse it, open PDFs / pictures / songs / videos straight from it, hold a file to copy it to Luna, **Backup to USB**, **Eject**.
* **PDF reader** (poppler): swipe pages, zoom, jump to a page, remembers where you stopped. Voice: "Luna, read PDF <name>", "read this page" (she reads aloud and turns pages), "stop reading", "next page", "go to page 5", "zoom in".
* Needs `poppler-utils` (installed by `scripts/install.sh`).
