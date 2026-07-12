#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/docker/docker-compose.yml"

echo "============================================"
echo " RViz2 Visualization — Windows (WSL2)"
echo "============================================"

if [ -z "${DISPLAY:-}" ]; then
  echo "ERROR: DISPLAY is not set."
  echo ""
  echo " 1. Install VcXsrv (https://vcxsrv.sourceforge.io/)"
  echo " 2. Launch XLaunch with:"
  echo "     - Multiple windows"
  echo "     - Display number: 0"
  echo "     - Start no client"
  echo "     - Check 'Disable access control'"
  echo " 3. Find your Windows host IP:"
  echo "     ipconfig  (in PowerShell)"
  echo " 4. Export DISPLAY in WSL2:"
  echo "     export DISPLAY=192.168.1.100:0"
  echo "    Add it to ~/.bashrc to make it permanent."
  echo ""
  echo " Windows 11 with WSLg: X11 works automatically,"
  echo " no VcXsrv needed."
  exit 1
fi

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
  ros2 \
  ros2 launch mock_hmi_core visualize.launch.py
