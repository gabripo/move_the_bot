#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/docker/docker-compose.yml"

echo "Stopping all services..."

docker compose -f "$COMPOSE_FILE" --profile ollama-agent down 2>/dev/null
docker compose -f "$COMPOSE_FILE" --profile openclaw-agent down 2>/dev/null
docker compose -f "$COMPOSE_FILE" --profile all down 2>/dev/null

echo "Done."
