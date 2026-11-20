# Luna v2 — Desk Assistant Pet Robot

<p align="center">
  <img src="assets/screenshots/01-home-screen.png" alt="Luna v2 home screen" width="800">
</p>

<p align="center">
  <b>An interactive desktop companion combining offline voice interaction, face recognition, environmental monitoring, secure media storage, USB file browsing, calendar reminders, Wi-Fi switch control, and Telegram alerts.</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Platform-Raspberry%20Pi%204-red" alt="Raspberry Pi 4">
  <img src="https://img.shields.io/badge/Controller-ESP32-blue" alt="ESP32">
  <img src="https://img.shields.io/badge/Interface-Pygame-informational" alt="Pygame">
  <img src="https://img.shields.io/badge/Connectivity-Wi--Fi%20%7C%20USB%20%7C%20Telegram-success" alt="Connectivity">
</p>

---

## Table of contents

- [1. Project overview](#1-project-overview)
- [2. Key features](#2-key-features)
- [3. System architecture](#3-system-architecture)
- [4. Hardware requirements](#4-hardware-requirements)
- [5. Hardware connections](#5-hardware-connections)
- [6. Software stack](#6-software-stack)
- [7. Installation and setup](#7-installation-and-setup)
- [8. ESP32 switch controller setup](#8-esp32-switch-controller-setup)
- [9. Telegram bot setup](#9-telegram-bot-setup)
- [10. Voice commands](#10-voice-commands)
- [11. User interface gallery](#11-user-interface-gallery)
- [12. Security and privacy](#12-security-and-privacy)
- [13. Project data and directory structure](#13-project-data-and-directory-structure)
- [14. Testing and validation](#14-testing-and-validation)
- [15. Troubleshooting](#15-troubleshooting)
- [16. Safety notes](#16-safety-notes)
- [17. Current validation status and limitations](#17-current-validation-status-and-limitations)
- [18. Future improvements](#18-future-improvements)
- [19. Credits](#19-credits)
- [20. License](#20-license)

---

## 1. Project overview

**Luna v2** is a Raspberry Pi-powered desk assistant pet robot designed to act as an interactive desktop companion and a local smart-home interface. It combines a graphical robot face, voice interaction, camera-based face recognition, environmental sensing, local media management, personal reminders, security monitoring, and ESP32-operated physical switches.

The main application runs on a **Raspberry Pi 4 Model B (4 GB)**. An ESP32 DevKit acts as a separate Wi-Fi switch node and controls up to four MG90/MG90S micro servos. The servos physically move the plastic rocker of a wall switch from the outside; they are not connected to the mains wiring.

The v2 build extends the original desk assistant with six major additions:

1. A protected hidden gallery with PIN/password authentication and lockout.
2. Automatic USB drive monitoring and a universal file explorer.
3. A calendar with birthdays, anniversaries, custom events, reminders, and recognition-triggered wishes.
4. ESP32 + MG90 servo-based switch actuation over Wi-Fi.
5. A Control Center for registering ESP32 nodes and operating their switches.
6. A Telegram bot for media transfer, room status, security commands, and alerts.

### Design goals

- Provide an approachable, expressive desktop robot interface.
- Keep core voice interaction local using an offline speech-recognition model.
- Separate the main application from switch-driving hardware.
- Keep slow network, storage, and USB operations off the graphical interface thread.
- Protect hidden media from casual access through an authenticated application vault.
- Provide remote notifications and commands through a Telegram bot.
- Make the system modular so sensors, ESP32 nodes, and application features can be tested independently.

---

## 2. Key features

| Feature | Description |
|---|---|
| Animated robot interface | Full-screen pet-style face and touch/wake interaction |
| Offline voice interface | Vosk-based speech recognition and wake-word/command flow |
| Face recognition | USB webcam and OpenCV-based recognition; people can be assigned permission ranks |
| Environmental monitoring | DHT22 temperature/humidity and MQ-2 gas/smoke sensing; optional ADS1115 and BMP280 |
| Secure hidden gallery | PIN or password, PBKDF2-HMAC-SHA256 password verification, session timeout, persistent lockout |
| Gallery | Browse locally stored pictures and videos |
| USB explorer | Detect mounted pen drives, browse files, open supported formats, copy media, and safely eject |
| Document reader | PDF viewing and text/Markdown reading with read-aloud support |
| Calendar | Monthly calendar, birthdays, anniversaries, custom events, and recurring events |
| Personal reminders | Day-before reminder at the configured time, with spoken reminder and chime |
| Birthday wishes | Recognised person can receive a birthday/anniversary greeting when the date matches |
| Wi-Fi switch controller | ESP32 REST API drives up to four MG90 servo switch actuators per node |
| Control Center | Add, rename, test, configure, and remove ESP32 nodes; operate individual switches |
| Telegram integration | Receive photos/videos, request status/snapshots, arm/disarm guard mode, receive alerts |
| Security/guard mode | Camera monitoring and intrusion notification workflow |

---

## 3. System architecture

### 3.1 Hardware architecture

The Raspberry Pi is the main processing unit. It handles the user interface, voice processing, camera recognition, sensor collection, calendar logic, file management, and Telegram communication.

The ESP32 is a separate actuator node. It joins the same 2.4 GHz Wi-Fi network and exposes a small HTTP REST API. Luna sends commands to the ESP32; the ESP32 runs the servo movement locally.

<p align="center">
  <img src="assets/build-guide/software-system-architecture.png" alt="Luna v2 software and hardware architecture from the build guide" width="850">
</p>

### 3.2 Main processing flow

```text
Microphone / Touch / Camera / Sensors / USB
                    |
                    v
          Raspberry Pi 4
       +----------------------+
       | Pygame application   |
       | Voice intent engine  |
       | Face recognition     |
       | Sensor manager       |
       | Calendar service     |
       | Vault / USB manager  |
       | Control Center       |
       | Telegram bot         |
       +----------------------+
          |       |       |
          |       |       +------ HTTPS ------ Telegram
          |       |
          |       +-------------- USB / local storage
          |
          +------ Wi-Fi HTTP REST ------ ESP32 node
                                            |
                                            +-- MG90 servo 1
                                            +-- MG90 servo 2
                                            +-- MG90 servo 3
                                            +-- MG90 servo 4
```

### 3.3 Software architecture principles

- The Pygame UI thread owns drawing and UI state.
- Long-running work such as HTTP requests, Telegram polling, file copying, and USB monitoring runs in worker/daemon threads.
- Worker results are passed back to the main application through an event queue.
- Face-recognition rank and configured permissions are checked before protected actions.
- ESP32 servo movement uses a non-blocking state machine so HTTP handling is not stalled by a servo movement.
- Exceptions in event handlers and frames are logged; recoverable failures should not terminate the complete Luna interface.

---

## 4. Hardware requirements

### 4.1 Main Luna hardware

| Component | Quantity | Purpose / notes |
|---|---:|---|
| Raspberry Pi 4 Model B, 4 GB | 1 | Main processing unit |
| 5 V / 3 A USB-C supply | 1 | Raspberry Pi power |
| microSD card, 32 GB Class 10 / A1 | 1 | Raspberry Pi OS and project files |
| 7-inch HDMI touch display, 1024 × 600 | 1 | Main interface |
| micro-HDMI cable | 1 | Display connection |
| MQ-2 gas sensor module | 1 | Gas/smoke indication; powered from 5 V |
| TTP223 touch module | 1 | Touch input |
| DHT22 sensor | 1 | Temperature and humidity |
| USB microphone | 1 | Voice input |
| USB webcam (UVC) | 1 | Face recognition and security snapshots |
| Bluetooth speaker | 1 | Voice output |
| 10 kΩ resistors | 2 | MQ-2 voltage divider |
| 20 kΩ resistors | 2 | MQ-2 voltage divider |
| ADS1115 (optional) | 1 | Analog gas-level measurement |
| BMP280 (optional) | 1 | Pressure measurement |

### 4.2 ESP32 switch-controller hardware

| Component | Quantity | Purpose / notes |
|---|---:|---|
| ESP32 DevKit (ESP32-WROOM-32) | 1 per room/node | Wi-Fi actuator controller |
| MG90/MG90S micro servo | 1–4 per ESP32 | Physical switch actuator |
| Regulated 5 V / 2 A supply | 1 per ESP32 node | Dedicated servo supply |
| 470 µF / 10 V electrolytic capacitor | 1 | Across servo 5 V and GND |
| Jumper wires / perfboard / terminals | As required | Connections |
| Servo bracket or double-sided foam tape | As required | Mechanical mounting |
| USB pen drive | 1 | Media import/export and file browsing |

### 4.3 Tools

- Computer with Raspberry Pi Imager.
- Arduino IDE 2.x for ESP32 firmware.
- Phone with Telegram.
- Multimeter for checking supply voltage and common ground.
- Screwdriver set and basic mounting tools.

---

## 5. Hardware connections

### 5.1 Raspberry Pi sensor and peripheral connections

The following table uses **physical pin numbers** on the Raspberry Pi 40-pin header.

| Component | Module pin | Raspberry Pi connection |
|---|---|---|
| DHT22 | + | Pin 1 — 3.3 V |
| DHT22 | OUT | Pin 7 — GPIO4 |
| DHT22 | − | Pin 9 — GND |
| TTP223 | VCC | Pin 17 — 3.3 V |
| TTP223 | I/O | Pin 11 — GPIO17 |
| TTP223 | GND | Pin 14 — GND |
| MQ-2 | VCC | Pin 2 — 5 V |
| MQ-2 | GND | Pin 6 — GND |
| MQ-2 digital output | DO through divider | Pin 13 — GPIO27 |
| MQ-2 analog output (optional) | AO through divider | ADS1115 A0 |
| ADS1115 (optional) | SDA | Pin 3 — GPIO2 / SDA |
| ADS1115 (optional) | SCL | Pin 5 — GPIO3 / SCL |
| BMP280 (optional) | SDA/SCL | Shared I²C bus |
| USB microphone | USB | Any USB port |
| USB webcam | USB | Any USB port |
| Touch display | HDMI | Raspberry Pi HDMI port 0 |
| Display touch | USB | Raspberry Pi USB port |

**Important — MQ-2 voltage divider:** The MQ-2 output may reach 5 V, while Raspberry Pi GPIO inputs are 3.3 V tolerant. Do not connect the sensor output directly to a Pi GPIO. Use the specified 10 kΩ series resistor and 20 kΩ resistor to GND, and take the signal from their junction. The software configuration assumes `MQ2_DIVIDER_RATIO = 1.5`.

<p align="center">
  <img src="assets/build-guide/raspberry-pi-sensor-wiring.png" alt="Raspberry Pi sensor wiring and pin table" width="850">
</p>

Additional installation notes:

- Keep the MQ-2 sensor away from the Raspberry Pi CPU and heat sources.
- Keep the DHT22 away from the Pi and MQ-2 heater to reduce temperature-reading bias.
- Mount the TTP223 behind a non-metallic surface no thicker than approximately 3 mm.
- A new MQ-2 sensor requires an initial burn-in period; allow warm-up time after power-up.

### 5.2 ESP32 and MG90 servo connections

The supplied build guide assigns the servo signal pins as follows:

| ESP32 pin | Servo |
|---|---|
| GPIO13 | MG90 #1 signal |
| GPIO14 | MG90 #2 signal |
| GPIO26 | MG90 #3 signal |
| GPIO27 | MG90 #4 signal |
| GND | Common ground |

Servo wire connections:

- Signal (orange/yellow) → assigned ESP32 GPIO.
- Red → external regulated 5 V servo supply positive.
- Brown/black → external supply GND.
- ESP32 GND must be connected to the external servo-supply GND.
- Fit the 470 µF capacitor across servo supply 5 V and GND, close to the servos.

<p align="center">
  <img src="assets/build-guide/esp32-mg90-servo-wiring.png" alt="ESP32 to four MG90 servo wiring diagram" width="850">
</p>

**Do not power MG90 servos from the ESP32 3.3 V pin or Raspberry Pi.** Use a separate servo supply. Insufficient current or a missing common ground can cause servo instability or ESP32 resets.

### 5.3 Mechanical switch actuation

The servo horn should rest in front of the centre of the plastic rocker when it is at its neutral angle. The configured movement angle pushes the rocker in one direction for ON and the opposite direction for OFF. Calibrate each servo after mounting.

The system controls the switch mechanically; it does not electrically measure whether a wall switch or appliance is actually powered. If someone manually operates the wall switch, the logical state shown by Luna may need to be synchronised by toggling it again.

---

## 6. Software stack

| Layer | Technology |
|---|---|
| Operating system | Raspberry Pi OS 64-bit with desktop |
| Main language | Python 3 |
| User interface | Pygame |
| Voice recognition | Vosk offline speech model |
| Computer vision | OpenCV and face-recognition components |
| Camera | USB UVC webcam |
| Sensor interface | Raspberry Pi GPIO and I²C |
| Switch-node firmware | Arduino framework for ESP32 |
| Servo control | ESP32Servo |
| ESP32 JSON handling | ArduinoJson 7 |
| Local network | Wi-Fi, HTTP REST, mDNS |
| Telegram | Telegram Bot HTTPS API using `requests` |
| Video playback | mpv |
| USB detection | Polling monitor; optional `pyudev` event support |
| Document display | PDF reader / text and Markdown viewer |

---

## 7. Installation and setup

> The supplied build guide refers to a project archive named `luna_desk_assistant_v2.zip`. This README documents the installation workflow for that archive; it does not contain the complete application source code or firmware.

### 7.1 Prepare Raspberry Pi OS

1. Install Raspberry Pi Imager on your computer.
2. Select **Raspberry Pi 4**.
3. Select **Raspberry Pi OS (64-bit) with desktop**.
4. Configure hostname, username, password, Wi-Fi, and SSH in the Imager settings.
5. Write the OS image to the microSD card.
6. Insert the card into the Pi and boot with the display, microphone, and webcam connected.

### 7.2 Update the Raspberry Pi

```bash
sudo apt update
sudo apt full-upgrade -y
```

### 7.3 Copy and install Luna

Copy `luna_desk_assistant_v2.zip` to the Raspberry Pi, then run:

```bash
cd ~
unzip -o luna_desk_assistant_v2.zip
cd desk_buddy
bash scripts/install.sh
sudo reboot
```

The installer is described as installing system packages, enabling I²C, configuring desktop auto-login and screen blanking, creating the Python virtual environment, downloading the Vosk voice model and face-recognition models, and configuring auto-start. It also installs networking and USB-related packages used by v2.

### 7.4 First-run hardware tests

Run the following from the `desk_buddy` directory:

```bash
# Bluetooth speaker pairing
bash scripts/pair_bluetooth.sh

# Sensors and touch pad
./venv/bin/python tools/test_sensors.py

# Audio input/output
./venv/bin/python tools/test_audio.py

# I2C devices (if fitted)
i2cdetect -y 1

# Webcam and face recognition
./venv/bin/python tools/test_camera.py

# MQ-2 clean-air calibration
./venv/bin/python tools/calibrate_mq2.py

# Start Luna
./venv/bin/python main.py
```

Expected I²C addresses when optional modules are connected:

- ADS1115: `0x48`
- BMP280: `0x76` or `0x77`

### 7.5 Run automated tests

```bash
python3 tests/test_logic.py
python3 tests/test_ui_smoke.py
python3 tests/test_app_flow.py
```

The supplied build guide reports 23 automated tests across these three test files.

### 7.6 Introduce the owner

On first use, introduce yourself in front of the webcam using the voice interaction described in the guide:

```text
Luna, my name is Koushik
```

The first person registered becomes the master. Add other people and configure their permissions through Settings and Privacy.

**Change the initial privacy PIN immediately after setup.** The supplied guide lists the initial privacy PIN as `0223`.

### 7.7 Optional local configuration

Create or edit `config_local.py` in the project directory. The build guide gives these examples:

```python
# Optional local overrides
ANTHROPIC_API_KEY = "your-key"
ESP32_API_KEY = ""
MPV_HWDEC = "auto"
CALENDAR_REMIND_HOUR = 9
```

Keep private keys and credentials out of public repositories. Use the configuration names and defaults from the actual supplied source archive when adding further overrides.

---

## 8. ESP32 switch controller setup

### 8.1 Install Arduino IDE support

1. Install Arduino IDE 2.x.
2. Open **File → Preferences**.
3. Add the Espressif board package URL:

```text
https://espressif.github.io/arduino-esp32/package_esp32_index.json
```

4. Open Boards Manager and install **esp32 by Espressif**.
5. Install these libraries from Library Manager:
   - ESP32Servo
   - ArduinoJson version 7

### 8.2 Configure and upload firmware

Open:

```text
firmware/esp32_switch/esp32_switch.ino
```

Set the Wi-Fi credentials and servo count in the sketch:

```cpp
WIFI_SSID = "YOUR_2_4_GHZ_WIFI";
WIFI_PASS = "YOUR_WIFI_PASSWORD";
NUM_SERVOS = 2;   // Set to the number actually connected (1 to 4)
```

The exact declaration syntax should be preserved from the supplied sketch. If API-key protection is enabled, configure the same key in the Pi's `ESP32_API_KEY` setting.

In Arduino IDE:

1. Select **ESP32 Dev Module**.
2. Select the correct serial port.
3. Upload the sketch.
4. If upload remains at `Connecting...`, hold the ESP32 BOOT button during connection.
5. Open Serial Monitor at **115200 baud**.
6. Note the IP address and confirm the node reports its online hostname.

### 8.3 REST API

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/info` | Node name, firmware version, servo count, and IP |
| GET | `/api/status` | Wi-Fi signal and per-servo status |
| POST | `/api/servo` | Command a servo to switch ON or OFF |
| POST | `/api/calibrate` | Store a servo's neutral angle |

Example request:

```bash
curl http://esp32-switch.local/api/info
curl http://esp32-switch.local/api/status
```

Command servo 0 ON:

```bash
curl -X POST http://esp32-switch.local/api/servo \
  -H "Content-Type: application/json" \
  -d '{"servo_id":0,"action":"on","angle":45}'
```

Test from the Raspberry Pi:

```bash
./venv/bin/python tools/test_esp32.py esp32-switch.local 0 on
```

The servo command accepts an action of `on` or `off`. The movement angle is constrained by the firmware to the documented range of 5–90 degrees.

### 8.4 Calibration

The neutral angle is the servo's resting position in front of the switch rocker. Example:

```bash
curl -X POST http://esp32-switch.local/api/calibrate \
  -H "Content-Type: application/json" \
  -d '{"servo_id":0,"neutral":95}'
```

If the ON/OFF directions are reversed, configure the corresponding `INVERT` entry in the ESP32 sketch and upload again. Adjust the default flick angle in the Pi configuration if the arm does not move the rocker far enough or pushes too strongly.

### 8.5 Add the node in Luna

1. Open **Menu → Control Center**.
2. Select **Nodes**.
3. Choose **Add ESP32**.
4. Enter the node's mDNS hostname or IP address.
5. Give the node a room name.
6. Test the connection.
7. Set the number of connected servos.
8. Open **Switchboard** to operate and rename individual switches.

The application periodically checks node status. Network requests run with a timeout in worker threads so an offline ESP32 should not freeze the main interface.

---

## 9. Telegram bot setup

### 9.1 Create a Telegram bot

1. Open Telegram and search for `@BotFather`.
2. Send `/newbot`.
3. Follow the prompts and copy the bot token.
4. Open your newly created bot and press Start.
5. Obtain your Telegram chat ID using `@userinfobot` or the bot's `getUpdates` response.
6. In Luna, open **Settings → Security → Telegram alerts**.
7. Enter the bot token and chat ID.
8. Select **Send test message**.

Do not publish the bot token or `data/telegram.json`. The bot is configured to obey only the authorised chat ID; messages from other chats are ignored and logged.

### 9.2 Supported commands

| Telegram command | Function |
|---|---|
| `/help` | Show the command list |
| `/room_status` | Request temperature, humidity, air-quality and available pressure information |
| `/snapshot` | Capture and send a webcam snapshot |
| `/arm_alarm` | Enable guard mode |
| `/disarm_alarm` | Disable guard mode |
| `/alarm_status` | Report armed/disarmed state, siren state, queued intrusion photos, and time |

### 9.3 Media transfer

Send a photo or supported video to the bot. Luna downloads it into the local gallery and displays a notification. The guide documents a configurable Telegram media-download limit with a default of 20 MB.

### 9.4 Alerts

Luna can send:

- Gas/smoke alerts when the MQ-2 reading crosses its configured threshold.
- Repeated gas alerts while the condition remains active, followed by an all-clear message.
- Intrusion photographs captured while guard mode is armed, with date, time, and siren status in the caption.
- Delayed uploads of queued intrusion photographs when connectivity returns.

---

## 10. Voice commands

The following are examples documented for the Luna v2 interface. Recognition depends on the microphone, speech model, configured permissions, and a clear wake-word utterance.

| Example phrase | Action |
|---|---|
| “Luna, open USB” | Open the USB explorer |
| “Luna, eject the USB” | Safely eject the mounted drive |
| “Luna, open calendar” | Open the calendar |
| “Luna, what is on my calendar today?” | Read today's events |
| “Luna, what is on my calendar tomorrow?” | Read tomorrow's events |
| “Luna, any events coming up?” | Read upcoming events |
| “Luna, open control center” | Open the Control Center |
| “Luna, turn on the light” | Operate the matching switch |
| “Luna, turn off the fan” | Turn the named switch off |
| “Luna, open the hidden gallery” | Request vault authentication |

Switch names can be customised in Control Center. Voice operation is subject to the configured user-rank permissions.

---

## 11. User interface gallery

The following screenshots are taken from the supplied **Luna v2 Screens.pdf** and are included in this repository package.

### 11.1 Home screen

<p align="center">
  <img src="assets/screenshots/01-home-screen.png" alt="Luna robot home screen" width="800">
</p>

The home screen presents Luna's expressive face, USB connection indicator, temperature, humidity, time, and the prompt to say “Luna” or touch the pad.

### 11.2 Main menu

<p align="center">
  <img src="assets/screenshots/02-main-menu.png" alt="Luna main menu" width="800">
</p>

The menu provides access to Gallery, Music, Movies, Documents, USB Drive, Calendar, Control Center, Security, Weather, Games, and Settings.

### 11.3 Hidden gallery vault

<p align="center">
  <img src="assets/screenshots/03-hidden-gallery-vault.png" alt="Hidden gallery PIN screen" width="800">
</p>

The hidden gallery requests a PIN or password. The documented lockout is three incorrect attempts followed by a 30-second lock period, with subsequent lockouts increasing.

### 11.4 Gallery and Telegram media

<p align="center">
  <img src="assets/screenshots/04-gallery.png" alt="Luna gallery with media items" width="800">
</p>

The gallery displays local media and media received through Telegram.

### 11.5 USB file explorer

<p align="center">
  <img src="assets/screenshots/05-usb-file-explorer.png" alt="USB file explorer" width="800">
</p>

The explorer shows folders and supported files, including pictures, videos, PDFs, text files, and Markdown files. It also provides an eject action.

### 11.6 Text and Markdown reader

<p align="center">
  <img src="assets/screenshots/06-text-markdown-reader.png" alt="Markdown reader with text size and read aloud controls" width="800">
</p>

The text reader supports text-size controls and read-aloud functionality.

### 11.7 Calendar

<p align="center">
  <img src="assets/screenshots/07-calendar-month-view.png" alt="Luna monthly calendar" width="800">
</p>

The calendar uses different markers for birthdays, anniversaries, and custom events.

### 11.8 Add event

<p align="center">
  <img src="assets/screenshots/08-calendar-add-event.png" alt="Calendar event creation screen" width="800">
</p>

Events can be associated with a person Luna knows or entered as a custom event. Recurrence can be yearly or limited to one day.

### 11.9 Control Center — nodes

<p align="center">
  <img src="assets/screenshots/09-control-center-nodes.png" alt="Control Center ESP32 nodes" width="800">
</p>

The Nodes view lists ESP32 controllers and their online/offline status, address, and servo count.

### 11.10 Control Center — switchboard

<p align="center">
  <img src="assets/screenshots/10-control-center-switchboard.png" alt="Control Center switchboard" width="800">
</p>

The Switchboard displays individual switches and their logical ON/OFF state.

### 11.11 Security guard mode

<p align="center">
  <img src="assets/screenshots/11-security-guard-mode.png" alt="Luna security guard mode" width="800">
</p>

Guard mode changes the interface to a security state and uses the camera/intrusion workflow.

### 11.12 Telegram alerts

<p align="center">
  <img src="assets/screenshots/12-telegram-alerts.png" alt="Telegram alerts configuration and example messages" width="800">
</p>

The Telegram settings screen accepts the bot token and chat ID and displays example status and alert messages.

---

## 12. Security and privacy

### 12.1 Hidden gallery

The hidden gallery uses a `VaultManager` to control access to `data/hidden/`.

- PIN/password verification uses PBKDF2-HMAC-SHA256 with a random salt and 150,000 rounds.
- Three incorrect attempts trigger a lockout starting at 30 seconds.
- Lockout duration doubles on successive lockout rounds.
- Lockout state is persisted in `data/vault_state.json`.
- The vault session expires after 90 seconds of inactivity by default.
- Leaving the hidden gallery locks the vault.
- The hidden directory is restricted to the owning user with directory mode `700`.

**Security limitation:** this is an application-level access-control feature, not full-disk encryption. Someone with physical access to the microSD card may be able to read stored files using another system.

### 12.2 Telegram access

- Configure only your own chat ID as the authorised chat.
- Do not expose the bot token.
- If a token is exposed, revoke it using BotFather and configure a replacement.
- Avoid committing `data/telegram.json` or local configuration files to a public repository.

### 12.3 ESP32 network security

The ESP32 node communicates over the local network. The guide supports an optional shared API key. Keep the node on a trusted home network and configure the same key on the ESP32 and Raspberry Pi when API-key protection is enabled.

### 12.4 Face-based permissions

The application uses user ranks (master, priority, least-priority, and unknown) to determine whether certain actions are allowed. The build guide identifies separate permissions for features such as Control Center, switches, and calendar.

---

## 13. Project data and directory structure

The supplied build guide identifies the following important files and modules. The exact full repository tree should be taken from the accompanying source ZIP.

```text
desk_buddy/
├── main.py
├── app.py
├── config.py
├── config_local.py              # local secrets and overrides; do not publish
├── requirements.txt
│
├── buddy/
│   ├── app.py
│   ├── brain.py
│   ├── vault.py                 # secure hidden gallery
│   ├── usbmon.py                # USB detection and safe eject
│   ├── textview.py              # TXT / Markdown reader
│   ├── calendar_mgr.py          # events, reminders and greetings
│   ├── control_center.py        # ESP32 REST client and UI
│   └── telegram_bot.py          # Telegram polling and alerts
│
├── firmware/
│   └── esp32_switch/
│       └── esp32_switch.ino
│
├── data/
│   ├── gallery/
│   ├── hidden/
│   ├── hidden_pin.json
│   ├── vault_state.json
│   ├── calendar.json
│   ├── calendar_state.json
│   ├── esp32.json
│   ├── switch_log.jsonl
│   └── telegram.json
│
├── logs/
│   └── buddy.log
│
├── scripts/
│   ├── install.sh
│   └── pair_bluetooth.sh
│
├── tools/
│   ├── test_sensors.py
│   ├── test_audio.py
│   ├── test_camera.py
│   ├── calibrate_mq2.py
│   ├── test_esp32.py
│   └── test_telegram.py
│
├── tests/
│   ├── test_logic.py
│   ├── test_ui_smoke.py
│   └── test_app_flow.py
│
└── docs/
    └── CHANGES_v1_to_v2.diff
```

### 13.1 Important data files

| File | Purpose |
|---|---|
| `data/calendar.json` | Calendar events |
| `data/calendar_state.json` | Reminder and greeting state |
| `data/esp32.json` | Registered ESP32 nodes and switch names/states |
| `data/switch_log.jsonl` | Timestamped switch action history |
| `data/hidden_pin.json` | Salted vault credential data |
| `data/vault_state.json` | Persistent failed-attempt and lockout state |
| `data/telegram.json` | Telegram bot configuration; keep private |
| `logs/buddy.log` | Application diagnostics and exception tracebacks |

---

## 14. Testing and validation

### 14.1 Automated software tests

The supplied guide reports **23 automated tests** covering:

- Vault lockout and access logic.
- Calendar event and reminder logic.
- ESP32 REST client behaviour against mock firmware.
- Telegram command parsing and media-download flow.
- Voice-intent handling.
- Regression testing for the hidden-gallery crash.
- UI screens drawn and tapped using a Pygame stub.

Run:

```bash
python3 tests/test_logic.py
python3 tests/test_ui_smoke.py
python3 tests/test_app_flow.py
```

### 14.2 On-device validation checklist

- [ ] Luna starts and displays the robot face.
- [ ] Touch input is detected.
- [ ] Microphone and speaker work.
- [ ] Temperature and humidity update.
- [ ] Webcam captures a frame and face recognition works.
- [ ] MQ-2 clean-air calibration completes.
- [ ] Hidden gallery opens only after successful authentication.
- [ ] Three incorrect vault attempts trigger lockout.
- [ ] Luna remains running when the vault is cancelled or a wrong PIN is entered.
- [ ] USB drive is detected and the USB indicator appears.
- [ ] JPG, MP4, PDF, TXT, and MD files open as supported.
- [ ] USB files can be copied to the correct Luna media folder.
- [ ] USB safe eject completes.
- [ ] Calendar events can be created and deleted.
- [ ] Day-before reminders work.
- [ ] Recognition-triggered birthday greeting works once per day.
- [ ] ESP32 responds to `/api/info` and `/api/status`.
- [ ] Servo ON/OFF movement works and returns to neutral.
- [ ] Control Center can add and operate an ESP32 node.
- [ ] Voice switch commands work for configured switch names.
- [ ] Telegram `/room_status` and `/snapshot` work.
- [ ] Telegram photo/video transfer works within the configured size limit.
- [ ] Guard-mode intrusion and gas/smoke alerts are received.

### 14.3 Testing status

The build guide distinguishes between software tests performed with mocks/stubs and hardware tests that must be performed on the actual device. It reports 23 passing automated tests, but explicitly states that real display/touch layout, Arduino sketch compilation, servo movement, live Telegram servers, mpv hardware decoding, and real USB mounting were not verified in that test environment. Complete the on-device checklist before treating the whole build as validated.

---

## 15. Troubleshooting

| Problem | Suggested check |
|---|---|
| Luna closes when the hidden-gallery padlock is tapped | Confirm the updated `buddy/app.py` and `buddy/mediaapps.py` are installed; inspect `logs/buddy.log` |
| `esp32-switch.local` does not resolve | Install/enable Avahi and `libnss-mdns`, or add the ESP32 IP address directly |
| ESP32 appears offline | Confirm 2.4 GHz Wi-Fi, power, IP address, and that Pi and ESP32 are on the same reachable network |
| API returns unauthorised | Confirm `ESP32_API_KEY` matches the key in the firmware |
| Servo twitches or ESP32 reboots | Use a separate 5 V servo supply rated for the load, common GND, and the 470 µF capacitor |
| Servo does not move far enough | Recalibrate neutral and adjust the configured flick angle |
| ON and OFF directions are reversed | Change the corresponding `INVERT` setting in the firmware |
| Switch state differs from physical wall switch | The system tracks the commanded logical state; manually resynchronise by toggling |
| Telegram bot does not respond | Check bot token, authorised chat ID, internet connection, and `tools/test_telegram.py` |
| Telegram video is not saved | Check the configured download-size limit; the guide documents a default limit of 20 MB |
| USB icon does not appear | Confirm the desktop mounted the drive and inspect `/media/$USER`; adjust `USB_ROOTS` if required |
| USB eject reports drive busy | Close the file currently open from the USB drive and retry |

Useful diagnostic commands:

```bash
# Check mounted USB drives
ls /media/$USER

# Check I2C devices
i2cdetect -y 1

# Test ESP32
./venv/bin/python tools/test_esp32.py esp32-switch.local 0 on

# Test Telegram
./venv/bin/python tools/test_telegram.py

# Inspect application log
tail -n 100 logs/buddy.log
```

---

## 16. Safety notes

1. **Mains electricity:** Wall switches carry dangerous mains voltage. The servo must only push the external plastic rocker. Do not open the switch plate or expose the servo, wiring, or mounting hardware to live terminals. Use a qualified electrician for any work involving mains wiring.
2. **Servo power:** Do not power MG90 servos from the ESP32 3.3 V output or Raspberry Pi. Use the separate regulated supply specified in the build guide.
3. **Common ground:** The ESP32 GND and external servo-supply GND must be connected.
4. **Gas sensor:** MQ-2 is a hobby sensor and is not a certified life-safety gas detector. Do not rely on Luna as a replacement for certified smoke, fire, or gas alarms.
5. **Testing gas response:** Follow safe sensor-testing practices. Never ignite a lighter or release flammable gas to test the sensor.
6. **Mechanical movement:** Secure servo mounts and keep fingers, cables, and loose objects clear of the servo horn and switch rocker.
7. **Privacy:** Inform people when a camera is used for recognition or security monitoring. Protect captured images and personal data.

---

## 17. Current validation status and limitations

The README describes the architecture and behaviour documented in the supplied Luna v2 build guide and screen designs. It should not be interpreted as proof that every hardware feature has been tested on the final physical build.

Known limitations stated in the guide include:

- Vault protection controls application access; it does not encrypt the microSD card.
- The ESP32 switch controller tracks commanded state and does not electrically sense the wall switch.
- The ESP32 REST interface is intended for a trusted local network; use the optional API key.
- Telegram media download has a configured size limit.
- USB detection expects the desktop environment to mount the drive.
- Actual display/touch, servo, live Telegram, USB mounting, and video hardware-decoding behaviour require on-device validation.
- MQ-2 readings are indicative and should not be treated as certified safety measurements.

---

## 18. Future improvements

Potential future development directions (not claims of features already implemented):

- Add encrypted storage for private media and credentials.
- Add authenticated HTTPS or a stronger local-network security model for ESP32 nodes.
- Add physical feedback sensors to verify actual wall-switch position.
- Add a battery backup and graceful shutdown monitor.
- Add a device-health dashboard for sensors, camera, audio, USB, network, and ESP32 nodes.
- Add a more detailed event and security audit history.
- Add automated hardware-in-the-loop testing for servo and sensor behaviour.
- Improve enclosure design, cable management, and modular service access.

---

## 19. Credits

**Project:** Luna v2 — Desk Assistant Pet Robot  
**Developer:** Koushik


---

## 20. License

No license was specified in the supplied build guide. Add a `LICENSE` file before publishing or accepting contributions. Until a license is selected, all rights remain with the respective copyright holder(s); do not assume that the project is open source.

---

<p align="center">
  <b>Luna v2 — A smarter, more interactive desktop companion.</b><br>
  Built with Raspberry Pi, ESP32, Python, computer vision, sensors, and robotics.
</p>
