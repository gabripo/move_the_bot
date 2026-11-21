#!/usr/bin/env bash
# Everything ready to record the demo, in one command:
#   1. move_the_bot runs here, with the object scanner (./run.sh --scan)
#   2. the GPU PC's AI is on: the language model (Ollama) and Idol (photos -> 3D) answer
#   3. the language model is loaded, so the first command does not wait for it
#   4. Chrome opens recording mode in its own window
#
#   ./record-demo.sh          set up and open the recording window
#   ./record-demo.sh off      afterwards: switch the GPU PC's AI off again
#   ./record-demo.sh check    only say what is ready and what is not
#
# The GPU PC is reached from .env: OLLAMA_URL and IDOL_URL (used by move_the_bot anyway), and, to
# switch its AI on and off from here, GPU_PC_SSH="user@address" plus, if needed, GPU_PC_SSH_KEY.
# On the PC this needs `ai-switch install` once (docker/ai-switch/ai-switch.sh): starting and
# stopping the two services then needs no password. Options of the page: REC_URL_OPTIONS in .env,
# such as "&llmpc=my%20gaming%20PC".
set -uo pipefail
cd "$(dirname "$0")"

[ -f .env ] && set -a && . ./.env && set +a
WEB="http://localhost:${WEB_PORT:-8080}"
OLLAMA="${OLLAMA_URL:-}"
IDOL="${IDOL_URL:-}"
MODEL="${OLLAMA_MODEL:-qwen2.5:7b-instruct}"

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
answers() { curl -fsS -m 3 "$1" >/dev/null 2>&1; }

pc() {   # run a command on the GPU PC
  [ -n "${GPU_PC_SSH:-}" ] || return 1
  local key=(); [ -n "${GPU_PC_SSH_KEY:-}" ] && key=(-i "${GPU_PC_SSH_KEY/#\~/$HOME}" -o IdentitiesOnly=yes)
  ssh -o ConnectTimeout=6 -o BatchMode=yes "${key[@]}" $GPU_PC_SSH "$@"
}

pc_ai() {   # $1 start|stop: both AI services on the PC, without a password (ai-switch's rule)
  # One unit per call: the rule allows each unit, not a list of them at once.
  pc "systemctl --no-ask-password $1 ollama && systemctl --no-ask-password $1 idol"
}

wait_for() {   # $1 url, $2 seconds
  local i; for ((i = 0; i < $2; i += 2)); do answers "$1" && return 0; sleep 2; done; return 1
}

check() {
  local all=0
  answers "$WEB/" && ok "move_the_bot: $WEB" || { bad "move_the_bot is not running here"; all=1; }
  answers "$WEB/scan/health" && ok "object scanner" || { bad "object scanner (./run.sh --scan)"; all=1; }
  if [ -n "$OLLAMA" ]; then
    answers "$OLLAMA/api/version" && ok "language model at $OLLAMA" || { bad "language model at $OLLAMA"; all=1; }
  fi
  if [ -n "$IDOL" ]; then
    answers "$IDOL/health" && ok "Idol (photos → 3D) at $IDOL" || { bad "Idol at $IDOL"; all=1; }
  fi
  return $all
}

case "${1:-}" in
  check) step "Ready to record?"; check; exit $? ;;
  off)
    step "Switching the GPU PC's AI off"
    if pc_ai stop; then ok "language model and Idol stopped; the GPU is free for games"
    else bad "could not reach the PC (GPU_PC_SSH in .env), or ai-switch is not installed there"; exit 1; fi
    exit 0 ;;
  ""|start) ;;
  *) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac

step "1. move_the_bot, with the object scanner"
if ! docker info >/dev/null 2>&1 && [ "$(uname)" = Darwin ]; then
  open -a Docker                                  # Docker Desktop quits now and then
  for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 3; done
  docker info >/dev/null 2>&1 && ok "Docker Desktop started" || bad "Docker Desktop does not start: open it by hand"
fi
if answers "$WEB/" && answers "$WEB/scan/health"; then
  ok "already running"
else
  ./run.sh --scan >/dev/null && wait_for "$WEB/scan/health" 180 && ok "started" || bad "did not start: ./run.sh logs"
fi

step "2. The GPU PC's AI"
need_pc=0
[ -n "$OLLAMA" ] && ! answers "$OLLAMA/api/version" && need_pc=1
[ -n "$IDOL" ] && ! answers "$IDOL/health" && need_pc=1
if [ $need_pc = 0 ]; then
  ok "already on"
elif pc_ai start; then
  ok "switched on"
else
  bad "off, and I cannot switch it on from here: click the AI icon in the PC's tray (or set GPU_PC_SSH in .env)"
fi
[ -n "$OLLAMA" ] && { wait_for "$OLLAMA/api/version" 120 && ok "language model answers" || bad "no answer from $OLLAMA"; }
[ -n "$IDOL" ] && { wait_for "$IDOL/health" 180 && ok "Idol answers" || bad "no answer from $IDOL"; }

step "3. Loading the language model ($MODEL)"
if [ -n "$OLLAMA" ] && answers "$OLLAMA/api/version"; then
  start=$SECONDS
  if curl -fsS -m 300 "$OLLAMA/api/generate" \
       -d "{\"model\":\"$MODEL\",\"prompt\":\"Say ready.\",\"stream\":false,\"keep_alive\":\"60m\"}" >/dev/null; then
    ok "loaded in $((SECONDS - start)) s, kept for an hour"
  else
    bad "it did not answer: is $MODEL downloaded on the PC? (ollama-server model $MODEL)"
  fi
else
  ok "skipped (no remote language model)"
fi

step "4. Recording window"
url="$WEB/?rec${REC_URL_OPTIONS:-}"
if [ "$(uname)" = Darwin ]; then
  open -na "Google Chrome" --args --app="$url" --window-size=1920,1080 && ok "Chrome: $url"
elif command -v google-chrome >/dev/null; then
  google-chrome --app="$url" --window-size=1920,1080 >/dev/null 2>&1 & ok "Chrome: $url"
else
  bad "open $url in Chrome"
fi

step "Ready"
check || true
cat <<'TEXT'

In the window: allow the camera and the microphone, press S (the scene), R (the opening title),
then V to record (Chrome asks which tab: this one). P pauses, V stops and saves to Downloads.
The keys and the script are in the column on the right, which is not recorded.
A scan uses the GPU PC for about 3 minutes and unloads the language model meanwhile.
Afterwards: ./record-demo.sh off
TEXT
