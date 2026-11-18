#!/usr/bin/env python3
"""The AI switch in the system tray of Desktop Mode (KDE Plasma on Bazzite).

An "AI" icon, green while the language model (Ollama) or the image-to-3D server (Idol) runs,
grey when both are off.
  left-click   all AI on or off, right now (the boot settings stay as they are)
  right-click  each service on its own, what runs, and the settings: by default nothing AI starts
             with the PC (`ai-switch default`), and Gaming Mode switches it off
No password: the polkit rule from `ai-switch install` lets this user start and stop these two
services. Switching off while a scan is being made asks first. Installed by `ai-switch install`,
started with Desktop Mode (~/.config/autostart), or by hand with `ai-switch tray`.
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

SERVICES = {"ollama": "Language model (Ollama)", "idol": "Photos → 3D (Idol)"}
UNITS = Path("/etc/containers/systemd")
GAMING = Path("/var/lib/ai-switch/gaming-mode")
SCAN_PROGRESS = "http://localhost:8001/progress"


def installed() -> list[str]:
    return [s for s in SERVICES if (UNITS / f"{s}.container").is_file()]


def active(service: str) -> bool:
    return subprocess.run(["systemctl", "is-active", "--quiet", service]).returncode == 0


def states() -> dict[str, bool]:
    return {s: active(s) for s in installed()}


def any_on(state: dict[str, bool]) -> bool:
    return any(state.values())


def tooltip(state: dict[str, bool], scanning: str = "") -> str:
    if not state:
        return "AI switch: no AI service is installed"
    lines = [f"AI: {'ON' if any_on(state) else 'OFF'}"]
    lines += [f"{SERVICES[s]}: {'running' if on else 'off'}" for s, on in state.items()]
    if scanning:
        lines.append(scanning)
    lines.append("Click: all on/off. Right-click: more.")
    return "\n".join(lines)


def scanning() -> str:
    """'Scanning "mug", photo 2 of 4' while Idol works on a scan, else ''."""
    try:
        with urllib.request.urlopen(SCAN_PROGRESS, timeout=0.5) as r:
            p = json.load(r)
    except (OSError, ValueError):
        return ""
    if p.get("state") != "running":
        return ""
    views = f", photo {p['view']} of {p['views']}" if p.get("views", 0) > 1 and p.get("view") else ""
    return f"Scanning \"{p.get('name', '')}\"{views}"


def switch(service: str, on: bool) -> str:
    """Start or stop now, without a password (polkit). Returns an error message or ''."""
    r = subprocess.run(["systemctl", "--no-ask-password", "start" if on else "stop", service],
                       capture_output=True, text=True)
    return "" if r.returncode == 0 else (r.stderr.strip() or f"could not {'start' if on else 'stop'} {service}")


def starts_with_pc() -> bool:
    """Whether any AI service starts at boot (`ai-switch default on`); off by default."""
    for s in installed():
        try:
            text = (UNITS / f"{s}.container").read_text()
        except OSError:
            continue
        if any(line.startswith("WantedBy=multi-user.target") for line in text.splitlines()):
            return True
    return False


def gaming_default() -> str:
    try:
        return GAMING.read_text().strip() or "off"
    except OSError:
        return "off"


def _import_qt():
    for binding in ("PySide6", "PyQt6", "PyQt5", "PySide2"):
        try:
            return tuple(__import__(f"{binding}.{m}", fromlist=[m]) for m in ("QtWidgets", "QtGui", "QtCore"))
        except ImportError:
            continue
    return None


def _single_instance():
    lock = open(Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "ai-switch-tray.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    return lock


def run_tray() -> int:
    qt = _import_qt()
    if qt is None:
        print("ai-switch tray: needs PySide6 or PyQt (Bazzite has PySide6).", file=sys.stderr)
        return 1
    QtWidgets, QtGui, QtCore = qt
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("AI switch")
    app.setDesktopFileName("ai-switch-tray")
    if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
        print("No system tray in this session (Gaming Mode?).", file=sys.stderr)
        return 0

    def icon(on: bool):
        """'AI' on a rounded square: green when on, grey when off. No icon theme needed."""
        pix = QtGui.QPixmap(64, 64)
        pix.fill(QtGui.QColor(0, 0, 0, 0))
        p = QtGui.QPainter(pix)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setBrush(QtGui.QColor("#2fb36d" if on else "#6c7086"))
        p.setPen(QtGui.QColor(0, 0, 0, 0))
        p.drawRoundedRect(4, 4, 56, 56, 14, 14)
        font = QtGui.QFont("Sans", 24)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QtGui.QColor("white"))
        p.drawText(pix.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "AI")
        p.end()
        return QtGui.QIcon(pix)

    icons = {True: icon(True), False: icon(False)}
    tray = QtWidgets.QSystemTrayIcon()
    menu = QtWidgets.QMenu()            # must outlive the tray

    def refresh():
        state = states()
        tray.setIcon(icons[any_on(state)])
        tray.setToolTip(tooltip(state, scanning()))

    def notify(title, text, warn=False):
        kind = QtWidgets.QSystemTrayIcon.MessageIcon.Warning if warn else QtWidgets.QSystemTrayIcon.MessageIcon.Information
        tray.showMessage(title, text, kind, 4000)

    def confirm_stop(services) -> bool:
        busy = scanning()
        if not busy or "idol" not in services:
            return True
        answer = QtWidgets.QMessageBox.question(
            None, "AI switch", f"{busy}. Switching Idol off stops this scan. Switch off anyway?")
        return answer == QtWidgets.QMessageBox.StandardButton.Yes

    def set_services(services, on):
        if not on and not confirm_stop(services):
            return
        errors = [e for s in services if (e := switch(s, on))]
        if errors:
            notify("AI switch", "\n".join(errors) + "\nRun `ai-switch install` once to allow this without a password.", warn=True)
        else:
            notify("AI switch", f"AI is {'on' if on else 'off'} for now." if len(services) > 1
                   else f"{SERVICES[services[0]]}: {'started' if on else 'stopped'}.")
        QtCore.QTimer.singleShot(800, refresh)

    def toggle_all():
        state = states()
        if state:
            set_services(list(state) if not any_on(state) else [s for s, on in state.items() if on],
                         not any_on(state))

    def build_menu():
        menu.clear()
        state = states()
        head = menu.addAction(f"AI: {'ON' if any_on(state) else 'OFF'}" + (f" · {scanning()}" if scanning() else ""))
        head.setEnabled(False)
        menu.addAction("Switch all AI off now" if any_on(state) else "Switch all AI on now").triggered.connect(toggle_all)
        menu.addSeparator()
        for s, on in state.items():
            a = menu.addAction(SERVICES[s])
            a.setCheckable(True)
            a.setChecked(on)
            a.triggered.connect(lambda checked, s=s: set_services([s], checked))
        menu.addSeparator()
        b = menu.addAction("Starts with the PC: " + ("yes" if starts_with_pc() else "no")
                           + "  (ai-switch default on|off)")
        b.setEnabled(False)
        g = menu.addAction("In Gaming Mode: " + ("AI off" if gaming_default() == "off" else "no change")
                           + "  (ai-switch gaming-mode)")
        g.setEnabled(False)
        menu.addAction("Quit tray").triggered.connect(app.quit)

    menu.aboutToShow.connect(build_menu)
    build_menu()
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: toggle_all()
                           if reason == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger else None)
    refresh()
    tray.show()
    timer = QtCore.QTimer()
    timer.timeout.connect(refresh)       # notices changes made elsewhere (terminal, Gaming Mode)
    timer.start(3000)
    return app.exec() if hasattr(app, "exec") else app.exec_()


if __name__ == "__main__":
    lock = _single_instance()            # held while the tray runs
    if lock is None:
        sys.exit(0)                      # already in the tray
    sys.exit(run_tray())
