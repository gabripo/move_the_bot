#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/docker/docker-compose.yml"
PROFILE="ollama-agent"

echo "============================================"
echo " Launching: $PROFILE"
echo " Compose:   $COMPOSE_FILE"
echo "============================================"

docker compose -f "$COMPOSE_FILE" --profile "$PROFILE" up --build "$@"
