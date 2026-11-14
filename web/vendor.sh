#!/usr/bin/env sh
# Copies the browser libraries the web app needs into web/vendor/, so it runs without a CDN.
# Used by docker/Dockerfile.web; run it by hand to serve web/ straight from disk.
set -eu
cd "$(dirname "$0")"
npm install --no-audit --no-fund --silent
rm -rf vendor
mkdir -p vendor/three/build vendor/three/examples/jsm vendor/urdf-loader vendor/mediapipe
cp node_modules/three/build/three.module.js node_modules/three/build/three.core.js vendor/three/build/ 2>/dev/null || \
  cp node_modules/three/build/three.module.js vendor/three/build/
for part in controls loaders renderers utils libs; do
  cp -r "node_modules/three/examples/jsm/$part" vendor/three/examples/jsm/
done
cp -r node_modules/urdf-loader/src vendor/urdf-loader/
cp node_modules/@mediapipe/tasks-vision/vision_bundle.mjs vendor/mediapipe/
cp -r node_modules/@mediapipe/tasks-vision/wasm vendor/mediapipe/
# The hand-tracking model (7.5 MB). Without it, hand control falls back to Google's CDN.
MODEL=https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
if command -v curl >/dev/null 2>&1; then
  curl -fsSL --max-time 120 -o vendor/mediapipe/hand_landmarker.task "$MODEL" || rm -f vendor/mediapipe/hand_landmarker.task
elif command -v wget >/dev/null 2>&1; then
  wget -q -T 120 -O vendor/mediapipe/hand_landmarker.task "$MODEL" || rm -f vendor/mediapipe/hand_landmarker.task
fi
echo "vendor/ ready"
