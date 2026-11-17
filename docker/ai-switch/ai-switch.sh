#!/usr/bin/env bash
# One switch for every AI service on the GPU PC: the language model (Ollama, ollama-server.sh)
# and the image-to-3D server (Idol, idol-server.sh). Off means: both stopped, and nothing uses the
# GPU's compute (ROCm) any more, so games get the whole GPU.
# Written for Bazzite (Fedora Atomic), like the two server scripts.
#
#   ./ai-switch.sh install     install as `ai-switch`, with the Gaming Mode default and a launcher
#
# Then:
#   ai-switch now              switch them on or off right now (no password; boot settings stay)
#   ai-switch off              stop everything AI and keep it off after a reboot
#   ai-switch on               start it again, with the boot settings it had before
#   ai-switch status           what runs, what starts at boot, who uses the GPU's compute
#   ai-switch gaming-mode off|keep
#                              off (the default): entering Steam's Gaming Mode stops the AI
#                              services, and Desktop Mode starts again those set to start at boot;
#                              keep: the modes change nothing
#
# The launcher "AI services on/off" runs `ai-switch now`; in Gaming Mode add it to Steam with
# "Add a Non-Steam Game" to switch the AI on for a while without leaving the game library.
set -euo pipefail

SERVICES=(ollama idol)                     # systemd units made by ollama-server and idol-server
UNITS=/etc/containers/systemd
STATE=/var/lib/ai-switch/boot              # boot settings saved by "off", restored by "on"
GAMING=/var/lib/ai-switch/gaming-mode      # off | keep
BIN=/usr/local/bin/ai-switch
POLKIT=/etc/polkit-1/rules.d/50-ai-switch.rules
SESSION_UNIT="$HOME/.config/systemd/user/ai-switch-session.service"
LAUNCHER="$HOME/.local/share/applications/ai-switch.desktop"
BOOT_LINE="WantedBy=multi-user.target"

installed() { [ -f "$UNITS/$1.container" ]; }
active() { systemctl is-active --quiet "$1"; }
boot() { grep -q "^$BOOT_LINE" "$UNITS/$1.container" 2>/dev/null && echo on || echo off; }
tool() { [ "$1" = ollama ] && echo ollama-server || echo idol-server; }
gaming_default() { cat "$GAMING" 2>/dev/null || echo off; }
in_gaming_mode() { [ -n "$(systemctl --user list-units --state=active --no-legend 'gamescope-session-plus@*' 2>/dev/null)" ]; }

# Start or stop a service now. The polkit rule from `install` lets this user do it without a
# password (also from a session with no terminal, such as Gaming Mode); sudo otherwise.
now() {
  systemctl --no-ask-password "$1" "$2" 2>/dev/null || sudo systemctl "$1" "$2"
}

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

# Right now, without touching the boot settings: off if anything runs, else on. No password
# needed once installed.
cmd_now() {
  if [ "$(state)" = on ]; then
    for s in "${SERVICES[@]}"; do installed "$s" && active "$s" && now stop "$s" && echo "Stopped $s."; done
    echo "AI is off for now (the boot settings are unchanged)."
  else
    for s in "${SERVICES[@]}"; do installed "$s" && now start "$s" && echo "Started $s."; done
    echo "AI is on for now. Language model: port 11434, image to 3D: port 8001."
  fi
}

# Run by the user unit at the start of every graphical session: Gaming Mode or Desktop Mode.
cmd_session() {
  [ "$(gaming_default)" = keep ] && { echo "gaming-mode keep: nothing to do"; return; }
  if in_gaming_mode; then
    for s in "${SERVICES[@]}"; do installed "$s" && active "$s" && now stop "$s" && echo "Gaming Mode: stopped $s."; done
  else
    for s in "${SERVICES[@]}"; do
      installed "$s" && [ "$(boot "$s")" = on ] && ! active "$s" && now start "$s" && echo "Desktop Mode: started $s."
    done
  fi
  return 0
}

cmd_gaming_mode() {
  case "${1:-}" in
    off|keep) sudo mkdir -p "$(dirname "$GAMING")" && echo "$1" | sudo tee "$GAMING" >/dev/null
              echo "Gaming Mode: $([ "$1" = off ] && echo "the AI services stop when it starts" || echo "changes nothing")." ;;
    *) echo "ai-switch gaming-mode off|keep   (now: $(gaming_default))"; exit 1 ;;
  esac
}

cmd_status() {
  for s in "${SERVICES[@]}"; do
    if installed "$s"; then
      printf '%-7s %-9s start at boot: %s\n' "$s" "$(systemctl is-active "$s" 2>/dev/null || true)" "$(boot "$s")"
    else
      printf '%-7s not installed\n' "$s"
    fi
  done
  echo "In Gaming Mode: $([ "$(gaming_default)" = off ] && echo "AI off" || echo "no change") (ai-switch gaming-mode off|keep)$(in_gaming_mode && echo "; Gaming Mode is running" || true)"
  local users; users=$(gpu_users)
  echo "GPU compute (ROCm) used by: ${users:-nothing}" | tr '\n' ' '; echo
}

cmd_install() {
  sudo install -m 755 "$0" "$BIN" 2>/dev/null || sudo cp "$0" "$BIN"
  # Only this user, only these two services, only start/stop/restart: what the Gaming Mode
  # default and the launcher need, with no terminal to type a password in.
  local units; units=$(printf '"%s.service", ' "${SERVICES[@]}")
  sudo tee "$POLKIT" >/dev/null <<RULES
// move_the_bot ai-switch: $USER may start and stop the AI services without a password.
polkit.addRule(function (action, subject) {
  if (action.id === "org.freedesktop.systemd1.manage-units" && subject.user === "$USER") {
    var units = [${units%, }];
    var verb = action.lookup("verb");
    if (units.indexOf(action.lookup("unit")) >= 0 &&
        (verb === "start" || verb === "stop" || verb === "restart")) {
      return polkit.Result.YES;
    }
  }
});
RULES
  sudo chmod 644 "$POLKIT"
  [ -f "$GAMING" ] || { sudo mkdir -p "$(dirname "$GAMING")"; echo off | sudo tee "$GAMING" >/dev/null; }

  mkdir -p "$(dirname "$SESSION_UNIT")"
  cat > "$SESSION_UNIT" <<UNIT
[Unit]
Description=AI services off in Gaming Mode, back in Desktop Mode (ai-switch gaming-mode)
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=$BIN session

[Install]
WantedBy=graphical-session.target
UNIT
  systemctl --user daemon-reload
  systemctl --user enable ai-switch-session.service >/dev/null 2>&1

  mkdir -p "$(dirname "$LAUNCHER")"
  cat > "$LAUNCHER" <<DESKTOP
[Desktop Entry]
Type=Application
Name=AI services on/off
Comment=Switch the language model and the image-to-3D server on or off for now (move_the_bot)
Exec=bash -c "$BIN now; sleep 4"
Terminal=true
Icon=preferences-system
Categories=System;
DESKTOP
  echo "Installed: ai-switch, the launcher \"AI services on/off\" in the application menu, and"
  echo "the Gaming Mode default (ai-switch gaming-mode: $(gaming_default))."
  cmd_status
}

case "${1:-now}" in
  now|toggle) cmd_now ;;
  on) cmd_on ;;
  off) cmd_off ;;
  session) cmd_session ;;
  gaming-mode) cmd_gaming_mode "${2:-}" ;;
  status) cmd_status ;;
  install) cmd_install ;;
  *) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
