#!/usr/bin/env bash
# Pair + trust + connect a Bluetooth speaker and remember it for auto-reconnect.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "Put your speaker in PAIRING mode now, then press Enter."; read -r _
bluetoothctl power on
bluetoothctl agent on
echo "Scanning for 15 seconds..."
bluetoothctl --timeout 15 scan on > /dev/null
echo; echo "Devices found:"; bluetoothctl devices
echo; read -rp "Type the MAC address of your speaker (AA:BB:CC:DD:EE:FF): " MAC
bluetoothctl pair "$MAC"
bluetoothctl trust "$MAC"
bluetoothctl connect "$MAC"
touch "$ROOT/config_local.py"
sed -i '/^BT_SPEAKER_MAC/d' "$ROOT/config_local.py"
echo "BT_SPEAKER_MAC = \"$MAC\"" >> "$ROOT/config_local.py"
echo "Saved. Luna will reconnect to $MAC automatically after every power-on."
