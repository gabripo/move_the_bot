"""Which 3D model draws an object: your own, the repo's, or none."""
from move_the_bot.models3d import find_model


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
