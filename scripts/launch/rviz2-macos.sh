#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/docker/docker-compose.yml"

echo "============================================"
echo " RViz2 Visualization — macOS"
echo "============================================"

# Require XQuartz
if ! command -v xquartz &>/dev/null 2>&1 && ! pgrep -x XQuartz &>/dev/null; then
  echo "ERROR: XQuartz is not running."
  echo "Install: brew install --cask xquartz"
  echo "Then:    open -a XQuartz"
  echo "And in XQuartz Settings > Security, check:"
  echo "  'Allow connections from network clients'"
  exit 1
fi

# Get active interface IP
ACTIVE_IF="en0"
if ipconfig getifaddr "$ACTIVE_IF" &>/dev/null; then
  HOST_IP=$(ipconfig getifaddr "$ACTIVE_IF")
else
  HOST_IP=$(ipconfig getifaddr en1)
fi

if [ -z "$HOST_IP" ]; then
  echo "ERROR: Could not determine host IP."
  exit 1
fi

# Ensure X11 access
xhost + "$HOST_IP" 2>/dev/null || true

echo ""
echo " Host IP:    $HOST_IP"
echo " Compose:    $COMPOSE_FILE"
echo ""
echo " Starting stack (background), then launching RViz2..."
echo ""

# Start the stack in background
docker compose -f "$COMPOSE_FILE" --profile ollama-agent up -d

echo ""
echo " Launching RViz2 (close with Ctrl+C)..."
echo ""

# Run RViz2 with X11 forwarding
docker compose -f "$COMPOSE_FILE" --profile ollama-agent run \
  --rm \
  -e DISPLAY="$HOST_IP":0 \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  ros2 \
  ros2 launch mock_hmi_core visualize.launch.py
