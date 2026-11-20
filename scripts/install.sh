#!/usr/bin/env bash
# Luna installer for Raspberry Pi OS (Bookworm / Trixie, 64-bit with Desktop)
# Run once:   bash scripts/install.sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
echo "==> Installing system packages"
sudo apt update
sudo apt install -y python3-venv python3-pip python3-dev python3-pygame python3-numpy \
    python3-gpiozero python3-lgpio python3-smbus libportaudio2 portaudio19-dev \
    espeak-ng mpg123 pulseaudio-utils bluez fonts-dejavu-core unzip wget i2c-tools \
    python3-opencv v4l-utils mpv brightnessctl network-manager poppler-utils udisks2 exfatprogs ntfs-3g \
    avahi-daemon avahi-utils libnss-mdns
sudo apt install -y libgpiod3 2>/dev/null || sudo apt install -y libgpiod2 || true

echo "==> Enabling I2C, desktop auto-login, no screen blanking"
sudo raspi-config nonint do_i2c 0 || true
sudo raspi-config nonint do_boot_behaviour B4 || true
sudo raspi-config nonint do_blanking 1 || true
sudo usermod -aG audio,gpio,i2c,video,bluetooth "$USER" || true

echo "==> Creating Python environment"
python3 -m venv --system-site-packages venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

echo "==> Downloading offline voice model (needs internet, ~50 MB)"
bash scripts/download_vosk_model.sh || echo "!! Model download failed - run scripts/download_vosk_model.sh later"

echo "==> Downloading face-recognition models (needs internet, ~40 MB)"
bash scripts/download_face_models.sh || echo "!! Face model download failed - run scripts/download_face_models.sh later"

chmod +x scripts/*.sh main.py tools/*.py
echo "==> Enabling auto-start at power-on"
bash scripts/enable_autostart.sh

echo
echo "Install finished. Next steps:"
echo "  1) Pair your Bluetooth speaker:   bash scripts/pair_bluetooth.sh"
echo "  2) Test the hardware:             ./venv/bin/python tools/test_sensors.py"
echo "  3) Test the webcam:               ./venv/bin/python tools/test_camera.py"
echo "  4) Reboot:                        sudo reboot"
echo "  5) Introduce yourself:            say \"Luna, my name is <your name>\"  (the first person becomes the master)"
