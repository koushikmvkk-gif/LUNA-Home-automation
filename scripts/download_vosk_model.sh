#!/usr/bin/env bash
# Downloads the small Indian-English Vosk model (works offline afterwards).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/models"
NAME="vosk-model-small-en-in-0.4"
if [ -d "$NAME" ]; then echo "Model already present."; exit 0; fi
wget -q --show-progress "https://alphacephei.com/vosk/models/$NAME.zip"
unzip -q "$NAME.zip" && rm "$NAME.zip"
echo "Model installed in models/$NAME"
echo "(Prefer US English?  Download vosk-model-small-en-us-0.15 and set VOSK_MODEL_DIR in config_local.py)"
