#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/docker/docker-compose.yml"

echo "============================================"
echo " RViz2 Visualization — Linux"
echo "============================================"

# Authorize local X11 connections
xhost +local: 2>/dev/null || true

echo ""
echo " DISPLAY:   $DISPLAY"
echo " Compose:   $COMPOSE_FILE"
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
  -e DISPLAY="$DISPLAY" \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v "$HOME/.Xauthority:/root/.Xauthority:ro" \
  ros2 \
  ros2 launch mock_hmi_core visualize.launch.py
