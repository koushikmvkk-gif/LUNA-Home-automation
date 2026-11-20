#!/usr/bin/env bash
# Downloads the two small OpenCV face models (YuNet detector + SFace recognizer) used for face recognition.
# They run fully offline on the Pi afterwards.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/models/face" && cd "$ROOT/models/face"
BASE="https://github.com/opencv/opencv_zoo/raw/main/models"
get() { [ -s "$2" ] && echo "$2 already present" || wget -q --show-progress -L -O "$2" "$1" || { rm -f "$2"; return 1; }; }
get "$BASE/face_detection_yunet/face_detection_yunet_2023mar.onnx" face_detection_yunet_2023mar.onnx
get "$BASE/face_recognition_sface/face_recognition_sface_2021dec.onnx" face_recognition_sface_2021dec.onnx
echo "Face models are in models/face"
echo "(If a download fails, get both .onnx files from https://github.com/opencv/opencv_zoo and copy them into models/face/)"
