#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/docker/docker-compose.yml"

. "$SCRIPT_DIR/_arch_detect.sh"

echo "============================================"
echo " RViz2 Visualization — macOS (VNC)"
echo "============================================"
echo ""
echo " This launches RViz2 via Xvfb (virtual framebuffer)"
echo " inside a dedicated container and shares it over VNC."
echo " Connect with Screen Sharing.app or any VNC"
echo " client to see the RViz2 window."
echo ""
echo " Rebuilding ros2 image..."
echo ""

docker compose -f "$COMPOSE_FILE" build ros2

echo ""
echo " Launching RViz2 on VNC port 5901..."
echo ""
echo " ==> Connect to localhost:5901 via Screen Sharing.app <=="
echo "     (Cmd+K in Finder, enter: vnc://localhost:5901)"
echo "     Password: rviz2"
echo ""
echo " Press Ctrl+C to stop."
echo ""

# Run a dedicated container for RViz2. Uses --no-deps to avoid
# pulling in ollama/agent-core, and --entrypoint to skip the
# model-pull entrypoint (not needed for visualization).
docker compose -f "$COMPOSE_FILE" --profile ollama-agent run \
  --rm \
  --no-deps \
  --entrypoint /rviz2_vnc.sh \
  -p 5901:5900 \
  ros2
