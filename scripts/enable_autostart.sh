#!/usr/bin/env bash
# Makes Luna start by itself as soon as the Pi finishes booting, and adds a desktop icon
# so you can start it again after saying "switch to Raspberry Pi".
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$HOME/.config/autostart" "$HOME/Desktop"
cat > "$HOME/.config/autostart/desk-buddy.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Luna
Exec=$ROOT/scripts/start_buddy.sh
Terminal=false
X-GNOME-Autostart-enabled=true
DESK
cat > "$HOME/Desktop/DeskLuna.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Start Luna
Comment=Back to robot assistant mode
Exec=env BUDDY_START_DELAY=0 $ROOT/scripts/start_buddy.sh
Terminal=false
Icon=face-smile
DESK
chmod +x "$HOME/Desktop/DeskLuna.desktop" "$ROOT/scripts/start_buddy.sh"
echo "Autostart enabled (and a 'Start Luna' icon was added to the desktop)."
