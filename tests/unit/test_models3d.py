"""Which 3D model draws an object: your own, the repo's, or none."""
from move_the_bot.models3d import find_model, save_scanned, scanned_size


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


def test_your_scan_beats_the_built_in_model_but_not_your_own(tmp_path):
    (tmp_path / "builtin").mkdir()
    (tmp_path / "builtin" / "mug.glb").write_bytes(b"glTF")
    scanned = save_scanned("mug", b"glTF", (0.08, 0.08, 0.1), str(tmp_path))
    assert find_model("mug", str(tmp_path), allow_download=False) == scanned
    (tmp_path / "local").mkdir()
    (tmp_path / "local" / "mug.glb").write_bytes(b"glTF")
    assert find_model("mug", str(tmp_path), allow_download=False) == "/models/local/mug.glb"


def test_not_scanned_means_no_size(tmp_path):
    assert scanned_size("teapot", str(tmp_path)) is None
