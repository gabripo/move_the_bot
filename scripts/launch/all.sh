#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/docker/docker-compose.yml"
PROFILE="all"

echo "============================================"
echo " Launching: $PROFILE (both agents)"
echo " Compose:   $COMPOSE_FILE"
echo "============================================"

# Build TypeScript dependencies
echo ""
echo "[1/3] Building OpenClaw tool plugin..."
cd "$PROJECT_DIR/agents/openclaw_agent/plugin" && npm install --silent && npx tsc

echo "[2/3] Building perception forwarder bridge..."
cd "$PROJECT_DIR/agents/openclaw_agent/bridge" && npm install --silent && npx tsc

cd "$PROJECT_DIR"

echo "[3/3] Starting Docker Compose..."
echo ""
docker compose -f "$COMPOSE_FILE" --profile "$PROFILE" up --build "$@"
