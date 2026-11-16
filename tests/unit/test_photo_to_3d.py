"""scripts/photo_to_3d.py: from an Idol Gaussian splat to a point-cloud GLB the scene can draw."""
import importlib.util
import json
import struct
from pathlib import Path

import numpy as np
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "photo_to_3d.py"
spec = importlib.util.spec_from_file_location("photo_to_3d", SCRIPT)
photo_to_3d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(photo_to_3d)

FIELDS = ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
          "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]


def splat(tmp_path, n=4000, seed=1):
    """A mug-like splat in Idol's frame: a cylinder 0.8 tall, y pointing down, a red side at +x."""
    rng = np.random.default_rng(seed)
    angle = rng.uniform(0, 2 * np.pi, n)
    height = rng.uniform(0, 0.8, n)
    rows = np.zeros(n, dtype=[(f, "<f4") for f in FIELDS])
    rows["x"], rows["z"] = 0.3 * np.cos(angle), 0.3 * np.sin(angle)
    rows["y"] = 0.4 - height                     # y down: the base (height 0) has the largest y
    red = np.cos(angle) > 0.9                    # the side the photo shows
    rows["f_dc_0"] = np.where(red, 1.5, -1.7)
    rows["f_dc_1"] = rows["f_dc_2"] = -1.7
    rows["opacity"] = 5.0
    rows["opacity"][: n // 10] = -5.0            # a tenth of them almost transparent
    rows["scale_0"] = rows["scale_1"] = rows["scale_2"] = -5.0
    header = "ply\nformat binary_little_endian 1.0\nelement vertex %d\n" % n
    header += "".join(f"property float {f}\n" for f in FIELDS) + "end_header\n"
    path = tmp_path / "mug.ply"
    path.write_bytes(header.encode() + rows.tobytes())
    return path


def test_reads_the_vertex_properties(tmp_path):
    v = photo_to_3d.read_ply(splat(tmp_path))
    assert set(FIELDS) <= set(v) and len(v["x"]) == 4000


def test_points_stand_up_on_their_footprint(tmp_path):
    points, colours = photo_to_3d.splat_to_points(photo_to_3d.read_ply(splat(tmp_path)), yaw_degrees=0)
    assert len(points) < 3700                    # the faint tenth is gone
    assert points[:, 1].min() == pytest.approx(0, abs=1e-6)
    assert points[:, 1].max() == pytest.approx(0.8, abs=0.02)
    assert np.abs(np.median(points[:, [0, 2]], 0)).max() < 0.03
    assert colours.min() >= 0 and colours.max() <= 1


def test_the_photographed_side_turns_towards_the_camera(tmp_path):
    points, colours = photo_to_3d.splat_to_points(photo_to_3d.read_ply(splat(tmp_path)))
    red = colours[:, 0] > 0.8
    angle = np.degrees(np.arctan2(points[red, 2].mean(), points[red, 0].mean()))
    assert angle == pytest.approx(photo_to_3d.FACE_CAMERA_YAW, abs=5)


def test_writes_a_point_cloud_glb(tmp_path):
    points, colours = photo_to_3d.splat_to_points(photo_to_3d.read_ply(splat(tmp_path)))
    target = tmp_path / "mug.glb"
    photo_to_3d.write_glb(target, points, colours)
    data = target.read_bytes()
    magic, version, length = struct.unpack("<III", data[:12])
    assert (magic, version, length) == (0x46546C67, 2, len(data))
    size, kind = struct.unpack("<II", data[12:20])
    doc = json.loads(data[20:20 + size])
    primitive = doc["meshes"][0]["primitives"][0]
    assert kind == 0x4E4F534A and primitive["mode"] == 0
    assert doc["accessors"][primitive["attributes"]["POSITION"]]["count"] == len(points)
    assert doc["accessors"][primitive["attributes"]["COLOR_0"]]["normalized"] is True
