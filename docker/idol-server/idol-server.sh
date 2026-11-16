#!/usr/bin/env bash
# Serve Idol (one photo -> 3D object) to your network, on a Linux PC with an AMD GPU, for the
# object scanner of move_the_bot (docs/your-own-objects.md). It runs the project's scan server
# with Idol on the GPU, in a container built here, as a system service, next to Ollama.
# Written for Bazzite (Fedora Atomic), like ollama-server.sh; needs Podman and systemd.
#
#   ./idol-server.sh install            build and set up; start now and at every boot
#   ./idol-server.sh install --no-boot  the same, but start only when you ask
#
# After install the script is available as `idol-server`:
#   idol-server login                  once: your Hugging Face token (Idol reads images through
#                                      two gated models; accept their terms first, see below)
#   idol-server test [PHOTO]           make a 3D object from a photo (default: Idol's avocado)
#   idol-server start | stop | restart run or stop the server now
#   idol-server boot on | off          start (or not) automatically at boot
#   idol-server status                 is it running, which GPU
#   idol-server logs                   follow the server's log
#   idol-server uninstall              remove the service (keeps the downloaded weights)
#
# Before `login`, accept the terms of these models with your Hugging Face account:
#   https://huggingface.co/facebook/dinov3-vith16plus-pretrain-lvd1689m
#   https://huggingface.co/black-forest-labs/FLUX.2-dev          (only its VAE is used)
# and create a read token at https://huggingface.co/settings/tokens
set -euo pipefail

GFX="${IDOL_GFX:-gfx1201}"                # the GPU: gfx1201 = Radeon RX 9070 (XT); gfx1100 = RX 7900...
MTB_REF="${MTB_REF:-master}"              # the move_the_bot branch the scan server comes from
IDOL_SDK="8db700349a5570aac390e4780fa32e3eed6b587a"      # speridlabs/idol-sdk, tested commit
IMAGE=localhost/idol-server
PORT="${IDOL_PORT:-8001}"
OLLAMA_PORT="${OLLAMA_PORT:-11434}"
UNIT=/etc/containers/systemd/idol.container
BIN=/usr/local/bin/idol-server
BOOT_LINE="WantedBy=multi-user.target"
TEST_PHOTO="https://raw.githubusercontent.com/speridlabs/idol-sdk/$IDOL_SDK/demo/examples/food-avocado.webp"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

build_image() {
  local dir raw="https://raw.githubusercontent.com/gabripo/move_the_bot/$MTB_REF"
  dir=$(mktemp -d)
  cat > "$dir/Containerfile" <<CONTAINERFILE
FROM docker.io/library/python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
# PyTorch for this GPU, from AMD's ROCm packages (only this GPU's kernels: a smaller download).
# The +rocm versions exist only there; PyPI is for their ordinary dependencies.
RUN pip install --no-cache-dir --index-url https://stable.repo.amd.com/rocm/whl-next/ \\
      --extra-index-url https://pypi.org/simple \\
      "torch[device-$GFX]==2.14.0+rocm10.1.0" "torchvision[device-$GFX]==0.29.0a0+rocm10.1.0"
# Idol without its dependencies, which are listed here instead: pip must not replace AMD's
# PyTorch with the NVIDIA one from PyPI.
RUN pip install --no-cache-dir --no-deps "idol @ git+https://github.com/speridlabs/idol-sdk@$IDOL_SDK" && \\
    pip install --no-cache-dir "transformers>=4.56" "diffusers>=0.40" "accelerate>=1.0" \\
      "huggingface_hub>=0.34" "safetensors>=0.4" "tensordict>=0.8" pillow plyfile tqdm \\
      fastapi uvicorn python-multipart requests numpy
# System libraries AMD's PyTorch and ROCm load but do not ship (found by reading the packages'
# ELF dependencies): OpenMP, libatomic, the OpenCL loader. After the big downloads, so a
# rebuild keeps them in Podman's cache.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libatomic1 ocl-icd-libopencl1 \\
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ADD $raw/docker/scan_server.py $raw/scripts/photo_to_3d.py /app/
ADD $raw/ros/move_the_bot/move_the_bot/models3d.py $raw/ros/move_the_bot/move_the_bot/world.py /app/
COPY check_gpu.py /app/
ENV IDOL_BACKEND=local MODELS_DIR=/tmp/idol-scan HF_HOME=/root/.cache/huggingface IDOL_PORT=8001
CMD ["sh", "-c", "uvicorn scan_server:app --host 0.0.0.0 --port \$IDOL_PORT"]
CONTAINERFILE
  cat > "$dir/check_gpu.py" <<'PY'
"""Run after the build: does PyTorch start, does it see the GPU, does Idol import?"""
import sys
try:
    import torch
except Exception as e:                    # typically a system library missing in the image
    print(f"PyTorch did not start: {e}")
    sys.exit(2)
print(f"PyTorch {torch.__version__}, ROCm {torch.version.hip}")
if not torch.cuda.is_available():
    print("PyTorch started, but it sees no GPU.")
    sys.exit(3)
print(f"GPU: {torch.cuda.get_device_name(0)}")
import idol  # noqa: E402,F401
print("Idol imports: ready.")
PY
  say "Building the Idol server image ($GFX; downloads PyTorch for ROCm, several GB, once)"
  sudo podman build --pull=newer -t "$IMAGE" "$dir"
  rm -rf "$dir"
  say "Checking that PyTorch starts, sees the GPU, and that Idol imports"
  local run=(sudo podman run --rm --device /dev/kfd --device /dev/dri --security-opt label=disable "$IMAGE")
  local code=0
  "${run[@]}" python /app/check_gpu.py || code=$?
  case $code in
    0) ;;
    2) echo "A system library is missing in the image. All the missing ones:"
       "${run[@]}" sh -c 'find /usr/local/lib/python3.12/site-packages -name "*.so*" -type f -print0 | xargs -0 ldd 2>/dev/null | grep "not found" | sort -u'
       exit 1 ;;
    3) echo "Is IDOL_GFX ($GFX) right for your card? Does /dev/kfd exist and work (rocminfo on the host)?"
       exit 1 ;;
    *) echo "The check failed (exit $code); the reason is above."; exit 1 ;;
  esac
}

write_unit() {   # $1: on|off (start at boot)
  local install="$BOOT_LINE"
  [ "$1" = off ] && install="# $BOOT_LINE    (boot start is off: idol-server boot on)"
  sudo mkdir -p "$(dirname "$UNIT")"
  sudo tee "$UNIT" >/dev/null <<UNIT
# Managed by idol-server (move_the_bot/docker/idol-server/idol-server.sh)
[Unit]
Description=Idol image-to-3D server for move_the_bot (AMD GPU, ROCm)
Wants=network-online.target
After=network-online.target ollama.service

[Container]
ContainerName=idol
Image=$IMAGE
# The GPU: compute (kfd) and render nodes (dri). SELinux would block them otherwise.
AddDevice=/dev/kfd
AddDevice=/dev/dri
SecurityLabelDisable=true
# Host network: the server is on port $PORT, and it reaches Ollama on this PC to make room.
Network=host
Environment=IDOL_PORT=$PORT
Environment=FREE_OLLAMA_URL=http://127.0.0.1:$OLLAMA_PORT
Environment=IDOL_KEEP_LOADED=0
# Idol's weights (about 3 GB) and your Hugging Face token stay in this volume.
Volume=idol-hf:/root/.cache/huggingface

[Service]
Restart=always
TimeoutStartSec=600

[Install]
$install
UNIT
  sudo systemctl daemon-reload
}

boot_state() { grep -q "^$BOOT_LINE" "$UNIT" 2>/dev/null && echo on || echo off; }

wait_ready() {
  for _ in $(seq 1 60); do
    curl -fsS --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && return 0
    sleep 2
  done
  echo "The Idol server did not answer on port $PORT. Look at: idol-server logs"; return 1
}

addresses() { hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.' || true; }

cmd_install() {
  local boot=on
  [ "${1:-}" = "--no-boot" ] && boot=off
  command -v podman >/dev/null || { echo "Podman is needed (Bazzite and Fedora have it)."; exit 1; }
  [ -e /dev/kfd ] || { echo "/dev/kfd is missing: ROCm cannot see the GPU on this system."; exit 1; }
  sudo -v
  build_image
  say "Installing the service (start at boot: $boot)"
  write_unit "$boot"
  sudo install -m 755 "$0" "$BIN" 2>/dev/null || sudo cp "$0" "$BIN"
  if command -v firewall-cmd >/dev/null && sudo firewall-cmd --state >/dev/null 2>&1; then
    say "Opening port $PORT in the firewall"
    sudo firewall-cmd --permanent --add-port="$PORT/tcp" >/dev/null && sudo firewall-cmd --reload >/dev/null
  fi
  say "Starting"
  sudo systemctl start idol
  wait_ready
  cmd_status
  say "Next: idol-server login   (once), then: idol-server test"
}

cmd_login() {
  echo "Paste a Hugging Face read token. Your account must have accepted the terms of:"
  echo "  facebook/dinov3-vith16plus-pretrain-lvd1689m and black-forest-labs/FLUX.2-dev"
  sudo podman exec -it idol hf auth login
}

cmd_test() {
  local photo="${1:-}" tmp
  tmp=$(mktemp -d)
  if [ -z "$photo" ]; then
    curl -fsSL -o "$tmp/photo.webp" "$TEST_PHOTO"; photo="$tmp/photo.webp"
  fi
  say "Making a 3D object from $(basename "$photo") (the first time also downloads Idol, about 3 GB)"
  local start=$SECONDS
  if curl -fsS --max-time 1200 -F "image=@$photo" -o "$tmp/splat.ply" "http://127.0.0.1:$PORT/splat"; then
    echo "OK: $(du -h "$tmp/splat.ply" | cut -f1) of 3D Gaussians in $((SECONDS - start)) s."
    echo "The scan server works. On the move_the_bot computer, in .env:"
    for ip in $(addresses); do echo "  IDOL_BACKEND=remote"; echo "  IDOL_URL=http://$ip:$PORT"; break; done
    echo "then: ./run.sh --scan"
  else
    echo "It failed. The reason is in: idol-server logs   (missing access to a gated model: idol-server login)"
  fi
  rm -rf "$tmp"
}

cmd_status() {
  echo "Service:       $(systemctl is-active idol 2>/dev/null || true)"
  echo "Start at boot: $(boot_state)"
  if curl -fsS --max-time 10 "http://127.0.0.1:$PORT/health" 2>/dev/null; then
    echo
    echo "Answers on:    $(for ip in $(addresses); do printf 'http://%s:%s ' "$ip" "$PORT"; done)"
  fi
}

case "${1:-}" in
  install)   shift; cmd_install "$@" ;;
  update)    build_image && sudo systemctl restart idol && wait_ready && echo "Updated and running." ;;
  login)     cmd_login ;;
  test)      shift; cmd_test "${1:-}" ;;
  start)     sudo systemctl start idol && wait_ready && echo "Running." ;;
  stop)      sudo systemctl stop idol && echo "Stopped." ;;
  restart)   sudo systemctl restart idol && wait_ready && echo "Running." ;;
  boot)      case "${2:-}" in
               on|off) [ -f "$UNIT" ] || { echo "Not installed yet: run install first."; exit 1; }
                       write_unit "$2"; echo "Start at boot: $(boot_state)" ;;
               *) echo "Usage: idol-server boot on|off  (now: $(boot_state))"; exit 1 ;;
             esac ;;
  status)    cmd_status ;;
  logs)      sudo journalctl -u idol -f ;;
  uninstall) sudo systemctl stop idol 2>/dev/null || true
             sudo rm -f "$UNIT" "$BIN"; sudo systemctl daemon-reload
             echo "Removed. The weights and your token stay in the Podman volume 'idol-hf' (sudo podman volume rm idol-hf)." ;;
  *)         sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
