"""docker/scan_server.py: several photos of an object become one model, with progress to watch.
Idol itself is replaced by a stand-in that answers each photo with a synthetic view."""
import importlib
import sys
import types
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("multipart")
from fastapi.testclient import TestClient  # noqa: E402

from test_photo_to_3d import photo_to_3d, view_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
# The scanner's container has these files side by side (docker/Dockerfile.scan).
for folder in ("docker", "scripts", "ros/move_the_bot/move_the_bot"):
    sys.path.insert(0, str(ROOT / folder))


@pytest.fixture
def scanner(tmp_path, monkeypatch):
    """The scan server with IDOL_BACKEND=local, a stand-in Idol and no GPU. Each photo k comes
    back as the object turned a quarter turn more; `seen` records the progress Idol was shown at."""
    seen = []

    class Pipeline:
        calls = 0

        def __call__(self, photo, mode, seed, num_gaussians):
            seen.append(server.progress())
            view = view_of(90 * Pipeline.calls, np.random.default_rng(Pipeline.calls))
            Pipeline.calls += 1
            return types.SimpleNamespace(gaussian=types.SimpleNamespace(
                save_ply=lambda path: Path(path).write_bytes(photo_to_3d.ply_bytes(view))))

    idol = types.ModuleType("idol")
    idol.IdolPipeline = types.SimpleNamespace(from_pretrained=lambda *a, **k: Pipeline())
    torch = types.ModuleType("torch")
    torch.version = types.SimpleNamespace(hip=None)
    torch.cuda = types.SimpleNamespace(is_available=lambda: False, empty_cache=lambda: None)
    monkeypatch.setitem(sys.modules, "idol", idol)
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setenv("IDOL_BACKEND", "local")
    monkeypatch.setenv("MODELS_DIR", str(tmp_path))
    monkeypatch.delenv("FREE_OLLAMA_URL", raising=False)
    server = importlib.reload(importlib.import_module("scan_server"))
    return TestClient(server.app), seen, tmp_path


def photos(n):
    return [("image", (f"view_{k}.jpg", b"\xff\xd8 a photo", "image/jpeg")) for k in range(n)]


def test_four_photos_become_one_model_seen_from_all_sides(scanner):
    client, seen, models = scanner
    r = client.post("/scan", data={"name": "a toy radio", "height_cm": "12"}, files=photos(4))
    assert r.status_code == 200, r.text
    answer = r.json()
    assert answer["name"] == "toy radio" and answer["views"] == 4
    # Found where they were taken: a quarter turn each (180 may come out as -180).
    for found, truth in zip(answer["angles"], (0, 90, 180, -90)):
        assert abs((found - truth + 180) % 360 - 180) <= 10, answer["angles"]
    assert (models / "cache").exists() and answer["model"].endswith(".glb")
    # Idol was shown each photo in turn, and the progress said so.
    assert [(p["step"], p["view"], p["views"]) for p in seen] == [("idol", k, 4) for k in (1, 2, 3, 4)]
    done = client.get("/progress").json()
    assert done["state"] == "done" and done["name"] == "toy radio"


def test_one_photo_still_works(scanner):
    client, seen, _ = scanner
    r = client.post("/scan", data={"name": "radio", "height_cm": "12"}, files=photos(1))
    assert r.status_code == 200, r.text
    assert r.json()["views"] == 1 and len(seen) == 1


def test_the_splat_endpoint_fuses_and_tells_the_angles(scanner):
    # What a GPU PC answers the scanner on the robot's machine (IDOL_BACKEND=remote).
    client, _, _ = scanner
    r = client.post("/splat", files=photos(4))
    assert r.status_code == 200
    assert len(r.headers["X-View-Angles"].split(",")) == 4
    assert len(photo_to_3d.parse_ply(r.content)["x"]) > 1000


def test_too_many_photos_are_refused(scanner):
    client, seen, _ = scanner
    r = client.post("/scan", data={"name": "radio", "height_cm": "12"}, files=photos(9))
    assert r.status_code == 400 and not seen
    assert client.get("/progress").json()["state"] == "failed"


def test_scans_are_listed_and_can_be_forgotten(scanner):
    client, _, _ = scanner
    assert client.post("/scan", data={"name": "radio", "height_cm": "12"}, files=photos(1)).status_code == 200
    assert [s["name"] for s in client.get("/scans").json()] == ["radio"]
    assert client.delete("/scans/the radio").json() == {"removed": "radio"}
    assert client.get("/scans").json() == []
    assert client.delete("/scans/radio").status_code == 404


def test_only_the_part_in_the_middle_is_kept(scanner):
    # The cut-out keeps the object held in the middle, not a speck elsewhere in the picture.
    import scan_server
    mask = np.zeros((100, 100), bool)
    mask[30:70, 35:65] = True          # the object
    mask[5:10, 80:95] = True           # something else
    kept = scan_server._around_center(mask)
    assert kept[50, 50] and kept[30:70, 35:65].all() and not kept[5:10, 80:95].any()
    assert not scan_server._around_center(np.zeros((100, 100), bool)).any()


def test_a_can_is_wrapped_from_its_cut_outs_not_idol(scanner, monkeypatch):
    client, seen, _ = scanner
    import scan_server
    from test_solid_mug import can_photos
    asked = {}

    def cut(photos, hands):
        asked["hands"] = hands
        return can_photos(90.0, n=len(photos))
    monkeypatch.setattr(scan_server, "cutouts", cut)
    hands = '[[[[0.1, 0.9], [0.2, 0.95], [0.3, 0.9], [0.2, 0.8], [0.15, 0.85]]], [], [], []]'
    r = client.post("/scan", data={"name": "monster drink", "height_cm": "17", "hands": hands}, files=photos(4))
    assert r.status_code == 200, r.text
    answer = r.json()
    assert answer["how"] == "wrapped" and answer["solid"] and answer["angles"] == [0, 90, 180, 270]
    assert abs(answer["size"][0] / answer["size"][2] - 104 / 260) < 0.05
    assert not seen                                       # Idol was not asked
    assert asked["hands"][0][0][0] == [0.1, 0.9] and asked["hands"][1] == []
    assert "monster" in " ".join(client.get("/health").json()["wrap_words"])


def test_a_can_goes_to_idol_when_it_cannot_be_cut_out(scanner, monkeypatch):
    client, seen, _ = scanner
    import scan_server

    def broken(photos, hands):
        raise RuntimeError("no SAM 2")
    monkeypatch.setattr(scan_server, "cutouts", broken)
    r = client.post("/scan", data={"name": "coke can", "height_cm": "12"}, files=photos(1))
    assert r.status_code == 200, r.text
    assert r.json()["how"] == "idol" and len(seen) == 1


def test_hands_are_erased_where_they_are():
    import scan_server
    hand = [[0.1, 0.6], [0.3, 0.6], [0.3, 0.9], [0.1, 0.9], [0.2, 0.75]]
    mask = scan_server.hand_mask([hand], 100, 100)
    assert mask[75, 20] and not mask[20, 80]
    assert scan_server._parse_hands("not json", 2) == [[], []]
    assert scan_server._parse_hands('[[[[0.5, 0.5]]]]', 3) == [[[[0.5, 0.5]]], [], []]
