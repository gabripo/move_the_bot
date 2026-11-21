#!/usr/bin/env bash
# Serve a language model to your network with Ollama, on a Linux PC with an AMD GPU.
# Uses the official ROCm container of Ollama, run by Podman as a system service.
# Written for Bazzite (Fedora Atomic); works on other Linux systems with Podman and systemd.
#
#   ./ollama-server.sh install            set everything up and start it now; it does not start
#                                         at boot (AI is off by default; ai-switch.sh)
#   ./ollama-server.sh install --boot     the same, and start it at every boot
#
# After install the script is available as `ollama-server`:
#   ollama-server start | stop | restart  run or stop the server now
#   ollama-server boot on | off           start (or not) automatically at boot
#   ollama-server status                  is it running, is it on the GPU, which models
#   ollama-server model [NAME]            download a model (default below)
#   ollama-server logs                    follow the server's log
#   ollama-server uninstall               remove the service (keeps downloaded models)
set -euo pipefail

IMAGE="${OLLAMA_IMAGE:-docker.io/ollama/ollama:rocm}"
MODEL="${OLLAMA_MODEL:-qwen2.5:14b-instruct-q4_K_M}"
PORT="${OLLAMA_PORT:-11434}"
UNIT=/etc/containers/systemd/ollama.container
BIN=/usr/local/bin/ollama-server
BOOT_LINE="WantedBy=multi-user.target"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
need_sudo() { sudo -v; }

write_unit() {   # $1: on|off (start at boot)
  local install="$BOOT_LINE"
  [ "$1" = off ] && install="# $BOOT_LINE    (boot start is off: ollama-server boot on)"
  sudo mkdir -p "$(dirname "$UNIT")"
  sudo tee "$UNIT" >/dev/null <<UNIT
# Managed by ollama-server (move_the_bot/docker/ollama-server/ollama-server.sh)
[Unit]
Description=Ollama language model server (AMD GPU, ROCm)
Wants=network-online.target
After=network-online.target

[Container]
ContainerName=ollama
Image=$IMAGE
# The GPU: compute (kfd) and render nodes (dri).
AddDevice=/dev/kfd
AddDevice=/dev/dri
# SELinux would otherwise block the container from opening the GPU devices.
SecurityLabelDisable=true
PublishPort=$PORT:11434
Volume=ollama:/root/.ollama
Environment=OLLAMA_CONTEXT_LENGTH=8192
# Free the video memory 10 minutes after the last request (games need it back).
Environment=OLLAMA_KEEP_ALIVE=10m
AutoUpdate=registry

[Service]
Restart=always
TimeoutStartSec=1800

[Install]
$install
UNIT
  sudo systemctl daemon-reload
}

boot_state() { grep -q "^$BOOT_LINE" "$UNIT" 2>/dev/null && echo on || echo off; }

wait_ready() {
  for _ in $(seq 1 60); do
    curl -fsS --max-time 2 "http://127.0.0.1:$PORT/api/version" >/dev/null 2>&1 && return 0
    sleep 2
  done
  echo "Ollama did not answer on port $PORT. Look at: ollama-server logs"; return 1
}

addresses() { hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.' || true; }

cmd_model() {
  local name="${1:-$MODEL}"
  say "Downloading $name (once; the 14B model is about 9 GB)"
  sudo podman exec ollama ollama pull "$name"
  say "Test answer, and where the model runs"
  sudo podman exec ollama ollama run "$name" "Answer with one word: ready?" --verbose 2>&1 | grep -E -i "ready|eval rate" || true
  sudo podman exec ollama ollama ps
  if sudo podman exec ollama ollama ps | grep -q "GPU"; then
    echo "OK: the model runs on the GPU."
  else
    echo "The model is NOT on the GPU. Check: sudo journalctl -u ollama | grep -i -E 'gpu|rocm|amdgpu'"
    echo "Alternative back-end: OLLAMA_IMAGE=docker.io/ollama/ollama:latest ollama-server install (Vulkan)"
  fi
}

cmd_install() {
  local boot=off                              # AI is off by default; --boot to start at boot
  [ "${1:-}" = "--boot" ] && boot=on
  command -v podman >/dev/null || { echo "Podman is needed (Bazzite and Fedora have it)."; exit 1; }
  [ -e /dev/kfd ] || echo "Warning: /dev/kfd is missing; ROCm may not see the GPU (Vulkan: see the end of this script's output)."
  need_sudo
  say "Downloading the Ollama ROCm image (several GB, once)"
  sudo podman pull "$IMAGE"
  say "Installing the service (start at boot: $boot)"
  write_unit "$boot"
  sudo install -m 755 "$0" "$BIN" 2>/dev/null || sudo cp "$0" "$BIN"
  if command -v firewall-cmd >/dev/null && sudo firewall-cmd --state >/dev/null 2>&1; then
    say "Opening port $PORT in the firewall"
    sudo firewall-cmd --permanent --add-port="$PORT/tcp" >/dev/null && sudo firewall-cmd --reload >/dev/null
  fi
  say "Starting"
  sudo systemctl start ollama
  wait_ready
  cmd_model "$MODEL"
  say "Done. Other computers in your network can use:"
  for ip in $(addresses); do echo "  http://$ip:$PORT"; done
  echo "  (or http://$(hostname).local:$PORT)"
  echo
  echo "Start at boot: $boot.  Change with: ollama-server boot on|off.  Stop now: ollama-server stop"
}

cmd_status() {
  echo "Service:       $(systemctl is-active ollama 2>/dev/null || true)"
  echo "Start at boot: $(boot_state)"
  if curl -fsS --max-time 2 "http://127.0.0.1:$PORT/api/version" >/dev/null 2>&1; then
    echo "Answers on:    $(for ip in $(addresses); do printf 'http://%s:%s ' "$ip" "$PORT"; done)"
    sudo podman exec ollama ollama list
    sudo podman exec ollama ollama ps
  fi
}

case "${1:-}" in
  install)   shift; cmd_install "$@" ;;
  start)     sudo systemctl start ollama && wait_ready && echo "Running." ;;
  stop)      sudo systemctl stop ollama && echo "Stopped (GPU memory is free)." ;;
  restart)   sudo systemctl restart ollama && wait_ready && echo "Running." ;;
  boot)      case "${2:-}" in
               on|off) [ -f "$UNIT" ] || { echo "Not installed yet: run install first."; exit 1; }
                       write_unit "$2"; echo "Start at boot: $(boot_state)" ;;
               *) echo "Usage: ollama-server boot on|off  (now: $(boot_state))"; exit 1 ;;
             esac ;;
  status)    cmd_status ;;
  model)     shift; cmd_model "${1:-}" ;;
  logs)      sudo journalctl -u ollama -f ;;
  uninstall) sudo systemctl stop ollama 2>/dev/null || true
             sudo rm -f "$UNIT" "$BIN"; sudo systemctl daemon-reload
             echo "Removed. Downloaded models stay in the Podman volume 'ollama' (sudo podman volume rm ollama)." ;;
  *)         sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
