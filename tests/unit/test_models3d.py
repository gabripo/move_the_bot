"""Which 3D model draws an object: your own, the repo's, or none."""
from move_the_bot.models3d import find_model, save_scanned, scanned_kinds, scanned_size


def test_own_model_comes_before_the_built_in_one(tmp_path):
    for folder in ("local", "builtin"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "mug.glb").write_bytes(b"glTF")
    assert find_model("mug", str(tmp_path), allow_download=False) == "/models/local/mug.glb"


def test_built_in_model_when_there_is_no_own_one(tmp_path):
    (tmp_path / "builtin").mkdir()
    (tmp_path / "builtin" / "mug.glb").write_bytes(b"glTF")
    assert find_model("mug", str(tmp_path), allow_download=False) == "/models/builtin/mug.glb"


def test_no_model_draws_the_basic_shape(tmp_path):
    assert find_model("teapot", str(tmp_path), allow_download=False) == ""


def test_a_scanned_object_keeps_its_model_and_size(tmp_path):
    path = save_scanned("stapler", b"glTF", (0.06, 0.03, 0.05), str(tmp_path))
    assert path.startswith("/models/cache/stapler_") and path.endswith(".glb")
    assert scanned_size("stapler", str(tmp_path)) == (0.06, 0.03, 0.05)
    assert find_model("stapler", str(tmp_path), allow_download=False) == path


def test_your_scan_beats_the_built_in_model(tmp_path):
    (tmp_path / "builtin").mkdir()
    (tmp_path / "builtin" / "mug.glb").write_bytes(b"glTF")
    scanned = save_scanned("mug", b"glTF", (0.08, 0.08, 0.1), str(tmp_path))
    assert find_model("mug", str(tmp_path), allow_download=False) == scanned


def test_the_newer_of_your_model_and_your_scan_wins(tmp_path):
    import os
    (tmp_path / "local").mkdir()
    own = tmp_path / "local" / "mug.glb"
    own.write_bytes(b"glTF")
    os.utime(own, (1_000_000, 1_000_000))
    scanned = save_scanned("mug", b"glTF", (0.08, 0.08, 0.1), str(tmp_path))
    assert find_model("mug", str(tmp_path), allow_download=False) == scanned   # scanned after
    own.touch()
    glb = tmp_path / scanned.removeprefix("/models/")
    os.utime(glb, (2_000_000, 2_000_000))
    assert find_model("mug", str(tmp_path), allow_download=False) == "/models/local/mug.glb"


def test_not_scanned_means_no_size(tmp_path):
    assert scanned_size("teapot", str(tmp_path)) is None


def test_scanned_kinds_lists_what_was_scanned(tmp_path):
    save_scanned("kaioken mug", b"glTF", (0.1, 0.1, 0.1), str(tmp_path))
    save_scanned("stapler", b"glTF", (0.06, 0.03, 0.05), str(tmp_path))
    assert sorted(scanned_kinds(str(tmp_path))) == ["kaioken mug", "stapler"]
