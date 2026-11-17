#!/usr/bin/env bash
# One switch for every AI service on the GPU PC: the language model (Ollama, ollama-server.sh)
# and the image-to-3D server (Idol, idol-server.sh). Off means: both stopped, neither starts at
# boot, and nothing uses the GPU's compute (ROCm) any more, so games get the whole GPU.
# Written for Bazzite (Fedora Atomic), like the two server scripts.
#
#   ./ai-switch.sh install     install as `ai-switch`, with a desktop launcher "AI services on/off"
#
# Then:
#   ai-switch off              stop everything AI and keep it off after a reboot
#   ai-switch on               start it again, with the boot settings it had before
#   ai-switch                  the other one (a toggle)
#   ai-switch status           what runs, what starts at boot, who uses the GPU's compute
#
# The launcher opens a terminal (for the password) and toggles; in Steam's Gaming Mode, add it
# with "Add a Non-Steam Game".
set -euo pipefail

SERVICES=(ollama idol)                     # systemd units made by ollama-server and idol-server
UNITS=/etc/containers/systemd
STATE=/var/lib/ai-switch/boot              # boot settings saved by "off", restored by "on"
BIN=/usr/local/bin/ai-switch
LAUNCHER="$HOME/.local/share/applications/ai-switch.desktop"
BOOT_LINE="WantedBy=multi-user.target"

installed() { [ -f "$UNITS/$1.container" ]; }
active() { systemctl is-active --quiet "$1"; }
boot() { grep -q "^$BOOT_LINE" "$UNITS/$1.container" 2>/dev/null && echo on || echo off; }
tool() { [ "$1" = ollama ] && echo ollama-server || echo idol-server; }

set_boot() {   # $1 service, $2 on|off: through the service's own script when it is there
  local t; t=$(tool "$1")
  if command -v "$t" >/dev/null; then "$t" boot "$2" >/dev/null
  elif [ "$2" = off ]; then sudo sed -i "s/^$BOOT_LINE/# $BOOT_LINE/" "$UNITS/$1.container" && sudo systemctl daemon-reload
  else sudo sed -i "s/^# *$BOOT_LINE.*/$BOOT_LINE/" "$UNITS/$1.container" && sudo systemctl daemon-reload
  fi
}

gpu_users() {  # programs that hold the GPU's compute device open (ROCm), read from /proc
  sudo sh -c 'for fd in /proc/[0-9]*/fd/*; do [ "$(readlink "$fd" 2>/dev/null)" = /dev/kfd ] && echo "$fd"; done' \
    | cut -d/ -f3 | sort -u | while read -r pid; do echo "$(cat "/proc/$pid/comm" 2>/dev/null) (pid $pid)"; done
}

state() { for s in "${SERVICES[@]}"; do installed "$s" && active "$s" && { echo on; return; }; done; echo off; }

cmd_off() {
  sudo -v
  sudo mkdir -p "$(dirname "$STATE")"
  : | sudo tee "$STATE" >/dev/null
  for s in "${SERVICES[@]}"; do
    installed "$s" || continue
    echo "$s=$(boot "$s")" | sudo tee -a "$STATE" >/dev/null
    sudo systemctl stop "$s" && echo "Stopped $s."
    set_boot "$s" off
  done
  local users; users=$(gpu_users)
  if [ -n "$users" ]; then
    echo "Still using the GPU's compute (ROCm):"; echo "$users" | sed 's/^/  /'
  else
    echo "AI is off: nothing uses the GPU's compute (ROCm), and nothing starts at boot."
  fi
}

cmd_on() {
  sudo -v
  for s in "${SERVICES[@]}"; do
    installed "$s" || continue
    # Back to the boot setting saved by "off"; never switched off before: leave it as it is.
    local was; was=$(sudo sed -n "s/^$s=//p" "$STATE" 2>/dev/null || true)
    was=${was:-$(boot "$s")}
    [ "$was" = "$(boot "$s")" ] || set_boot "$s" "$was"
    sudo systemctl start "$s" && echo "Started $s (start at boot: $was)."
  done
  echo "AI is on. Language model: port 11434, image to 3D: port 8001."
}

cmd_status() {
  for s in "${SERVICES[@]}"; do
    if installed "$s"; then
      printf '%-7s %-9s start at boot: %s\n' "$s" "$(systemctl is-active "$s" 2>/dev/null || true)" "$(boot "$s")"
    else
      printf '%-7s not installed\n' "$s"
    fi
  done
  local users; users=$(gpu_users)
  echo "GPU compute (ROCm) used by: ${users:-nothing}" | tr '\n' ' '; echo
}

cmd_install() {
  sudo install -m 755 "$0" "$BIN" 2>/dev/null || sudo cp "$0" "$BIN"
  mkdir -p "$(dirname "$LAUNCHER")"
  cat > "$LAUNCHER" <<DESKTOP
[Desktop Entry]
Type=Application
Name=AI services on/off
Comment=Switch the language model and the image-to-3D server on or off (move_the_bot)
Exec=bash -c "$BIN; read -rp 'Press Enter to close'"
Terminal=true
Icon=preferences-system
Categories=System;
DESKTOP
  echo "Installed: ai-switch, and the launcher \"AI services on/off\" in the application menu."
  cmd_status
}

case "${1:-toggle}" in
  on) cmd_on ;;
  off) cmd_off ;;
  toggle) if [ "$(state)" = on ]; then cmd_off; else cmd_on; fi ;;
  status) cmd_status ;;
  install) cmd_install ;;
  *) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
