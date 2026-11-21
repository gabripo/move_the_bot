#!/usr/bin/env bash
# Start or stop move_the_bot.
set -euo pipefail
cd "$(dirname "$0")"

usage() {
  cat <<'TEXT'
Usage: ./run.sh [options]        start (builds the images the first time)
       ./run.sh stop             stop everything
       ./run.sh logs             follow the robot's log

Options
  --host-ollama   use the Ollama app already running on this computer (fast on a Mac or a GPU PC)
  --ollama URL    use Ollama on another computer, e.g. --ollama http://gaming-pc.local:11434
                  (or set OLLAMA_URL in .env; docs/hardware-and-gpus.md shows how to serve it)
  --nim           use NVIDIA NIM in the cloud as language model (needs NVIDIA_API_KEY in .env)
  --no-llm        no language model at all: only the built-in rules understand commands
  --voice         also start local speech-to-text (Whisper); without it the browser's own is used
  --scan          also start the object scanner: show an object to the webcam, get it in 3D (Idol)
  --real [PORT]   drive a real SO-101 on USB (default port /dev/ttyACM0)
  --isaac         drive the arm simulated in NVIDIA Isaac Sim
  --rebuild       rebuild the images

Without options: simulated arm, and a small language model in an Ollama container.
TEXT
}

compose=(docker compose)
profiles=()
build=()
llm="container"
[ -f .env ] && set -a && . ./.env && set +a
# An OLLAMA_URL in .env means "use that Ollama": no need to start one in a container.
if [ -n "${OLLAMA_URL:-}" ]; then llm="remote"; fi

case "${1:-}" in
  stop) "${compose[@]}" --profile ollama --profile voice --profile scan down; exit 0 ;;
  logs) "${compose[@]}" logs -f robot; exit 0 ;;
  -h|--help|help) usage; exit 0 ;;
esac

while [ $# -gt 0 ]; do
  case "$1" in
    --host-ollama) llm="host" ;;
    --ollama) [ $# -gt 1 ] || { echo "--ollama needs a URL, e.g. http://192.168.1.50:11434"; exit 1; }
              llm="remote"; export OLLAMA_URL="$2"; shift ;;
    --nim) llm="nim" ;;
    --no-llm) llm="none" ;;
    --voice) profiles+=(--profile voice) ;;
    --scan) profiles+=(--profile scan) ;;
    --real) export HARDWARE=real
            if [ $# -gt 1 ] && [ "${2#--}" = "$2" ]; then export USB_PORT="$2"; shift; fi ;;
    --isaac) export HARDWARE=isaac ;;
    --rebuild) build=(--build) ;;
    *) echo "Unknown option: $1"; echo; usage; exit 1 ;;
  esac
  shift
done

case "$llm" in
  container) profiles+=(--profile ollama) ;;
  host) export OLLAMA_URL="http://host.docker.internal:11434" ;;
  nim)  export LLM_BACKEND=openai
        if [ -z "${OPENAI_API_KEY:-${NVIDIA_API_KEY:-}}" ]; then
          echo "Set NVIDIA_API_KEY (or OPENAI_API_KEY) in .env first: https://build.nvidia.com"; exit 1
        fi ;;
  none) export OLLAMA_URL="http://127.0.0.1:9" ;;
  remote)
    OLLAMA_URL="${OLLAMA_URL%/}"
    # Containers often cannot resolve names like gaming-pc.local, so resolve them here.
    name=$(printf '%s' "$OLLAMA_URL" | sed -E 's#^[a-z]+://([^/:]+).*#\1#')
    if ! printf '%s' "$name" | grep -Eq '^[0-9.]+$'; then
      ip=$( (getent ahostsv4 "$name" 2>/dev/null || true) | awk 'NR==1{print $1}')
      [ -z "$ip" ] && ip=$( (dscacheutil -q host -a name "$name" 2>/dev/null || true) | awk '/^ip_address/{print $2; exit}')
      if [ -n "$ip" ]; then OLLAMA_URL="${OLLAMA_URL/$name/$ip}"; fi
    fi
    export OLLAMA_URL
    if curl -fsS --max-time 5 "$OLLAMA_URL/api/version" >/dev/null 2>&1; then
      echo "Language model: Ollama at $OLLAMA_URL (${OLLAMA_MODEL:-default model})"
    else
      echo "Warning: no Ollama answers at $OLLAMA_URL. Simple commands will work; free-form ones"
      echo "will not until it does. Check: curl $OLLAMA_URL/api/version"
    fi ;;
esac

extra=()
if [ "${HARDWARE:-mock}" = "real" ]; then
  # A real arm needs its serial port inside the container.
  mkdir -p calibration
  extra=(-f docker-compose.yml -f docker/compose.real.yml)
elif [ "${HARDWARE:-mock}" = "isaac" ]; then
  # Isaac Sim runs on the host: the robot container joins the host network to share ROS topics.
  extra=(-f docker-compose.yml -f docker/compose.isaac.yml)
fi

# (the ${x[@]+...} form keeps the old bash shipped with macOS happy when an array is empty)
"${compose[@]}" ${extra[@]+"${extra[@]}"} ${profiles[@]+"${profiles[@]}"} up -d ${build[@]+"${build[@]}"}

port="${WEB_PORT:-8080}"
echo
echo "move_the_bot is starting. Open http://localhost:${port} (Chrome or Edge work best)."
echo "The first start downloads the language model (about 2 GB); simple commands work meanwhile."
echo "Stop with: ./run.sh stop"
