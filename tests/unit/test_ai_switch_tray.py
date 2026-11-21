"""docker/ai-switch/ai-switch-tray.py: what the tray icon says (no Qt, no systemd needed)."""
import importlib.util
import json
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / "docker" / "ai-switch" / "ai-switch-tray.py"
spec = importlib.util.spec_from_file_location("ai_switch_tray", PATH)
tray = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tray)


def test_on_while_any_service_runs():
    assert tray.any_on({"ollama": False, "idol": True})
    assert not tray.any_on({"ollama": False, "idol": False})


def test_tooltip_lists_each_service():
    text = tray.tooltip({"ollama": True, "idol": False}, 'Scanning "mug", photo 2 of 4')
    assert text.splitlines()[:4] == ["AI: ON", "Language model (Ollama): running", "Photos → 3D (Idol): off",
                                     'Scanning "mug", photo 2 of 4']


def test_scan_progress_is_read_from_idol(monkeypatch):
    class Answer:
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, *a): return self.body

    progress = {"state": "running", "name": "mug", "view": 2, "views": 4}
    monkeypatch.setattr(tray.urllib.request, "urlopen", lambda *a, **k: Answer(json.dumps(progress).encode()))
    assert tray.scanning() == 'Scanning "mug", photo 2 of 4'
    progress["state"] = "done"
    assert tray.scanning() == ""


def test_no_idol_means_no_scan(monkeypatch):
    def refuse(*a, **k): raise OSError("connection refused")
    monkeypatch.setattr(tray.urllib.request, "urlopen", refuse)
    assert tray.scanning() == ""


def test_starts_with_the_pc_only_when_a_unit_is_wanted_at_boot(tmp_path, monkeypatch):
    monkeypatch.setattr(tray, "UNITS", tmp_path)
    (tmp_path / "ollama.container").write_text("[Install]\n# WantedBy=multi-user.target    (boot start is off)\n")
    (tmp_path / "idol.container").write_text("[Install]\n# WantedBy=multi-user.target\n")
    assert not tray.starts_with_pc()
    (tmp_path / "idol.container").write_text("[Install]\nWantedBy=multi-user.target\n")
    assert tray.starts_with_pc()
