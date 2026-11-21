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


def test_real_size_follows_the_height_you_give(tmp_path):
    points, _ = photo_to_3d.splat_to_points(photo_to_3d.read_ply(splat(tmp_path)), yaw_degrees=0)
    width, depth, height = photo_to_3d.real_size(points, 0.1)
    assert height == 0.1
    assert width == pytest.approx(0.075, abs=0.006) and depth == pytest.approx(0.075, abs=0.006)


def view_of(turn_degrees, rng, n=6000):
    """What Idol would make of a photo of a mug turned by `turn_degrees`: a cylinder with a handle,
    red at its front (+x), blue at its back; true colours only on the photographed side (+x after
    the turn), grey elsewhere, as if invented. Idol's frame: y points down."""
    angle = rng.uniform(-np.pi, np.pi, n)
    height = rng.uniform(0, 0.8, n)
    body = np.stack([0.3 * np.cos(angle), 0.4 - height, 0.3 * np.sin(angle)], 1)
    t = rng.uniform(0, np.pi, n // 6)                         # a handle sticking out at +z
    handle = np.stack([0.03 * rng.standard_normal(n // 6), 0.4 - (0.4 + 0.2 * np.sin(t)),
                       0.3 + 0.15 * np.sin(t)], 1)
    xyz = np.concatenate([body, handle])
    true_side = np.degrees(np.arctan2(xyz[:, 2], xyz[:, 0]))  # in the object's own frame
    colour = np.full((len(xyz), 3), -1.0)                        # dark grey
    colour[np.abs(true_side) < 50] = (1.5, -1.7, -1.7)           # red front
    colour[np.abs(true_side) > 130] = (-1.7, -1.7, 1.5)          # blue back
    seen = photo_to_3d._turn(xyz[None], -turn_degrees)[0]        # the object turned in front of the camera
    photographed = np.abs(np.degrees(np.arctan2(seen[:, 2], seen[:, 0]))) < 60
    colour[~photographed] = (0.0, 0.0, 0.0)                     # invented: mid grey
    v = {"x": seen[:, 0], "y": seen[:, 1], "z": seen[:, 2],
         "f_dc_0": colour[:, 0], "f_dc_1": colour[:, 1], "f_dc_2": colour[:, 2],
         "opacity": np.full(len(xyz), 5.0), "scale_0": np.full(len(xyz), -5.0),
         "scale_1": np.full(len(xyz), -5.0), "scale_2": np.full(len(xyz), -5.0),
         "rot_0": np.ones(len(xyz)), "rot_1": np.zeros(len(xyz)), "rot_2": np.zeros(len(xyz)), "rot_3": np.zeros(len(xyz))}
    return {k: np.asarray(a, dtype=np.float64) for k, a in v.items()}


def test_one_view_invents_the_back_but_four_views_see_it():
    rng = np.random.default_rng(3)
    views = [view_of(k * 90, rng) for k in range(4)]
    fused, angles = photo_to_3d.fuse_splats(views, step=90)
    # Each view was turned by a quarter turn more (view_of turns the object by -k*90 degrees, so
    # +k*90 turns it back): found without being told which way round.
    assert [round(a) % 360 for a in angles] == pytest.approx([0, 90, 180, 270], abs=4)

    def back_colour(v):
        xyz = photo_to_3d._normalise(v)[0]
        back = np.degrees(np.abs(np.arctan2(xyz[:, 2], xyz[:, 0]))) > 150
        rgb = 0.5 + photo_to_3d.SH_C0 * np.stack([v["f_dc_0"], v["f_dc_1"], v["f_dc_2"]], 1)
        return rgb[back].mean(0)

    assert back_colour(views[0])[2] < 0.6                      # one photo: the back is invented grey
    assert back_colour(fused)[2] > 0.8 and back_colour(fused)[0] < 0.2   # four photos: really blue
    assert np.allclose(np.linalg.norm(np.stack([fused[f"rot_{i}"] for i in range(4)], 1), axis=1), 1)


def test_a_hand_under_the_object_does_not_move_its_centre():
    rng = np.random.default_rng(2)
    n = 6000
    a = rng.uniform(0, 2 * np.pi, n)
    h = rng.uniform(0, 1, n)
    xyz = np.stack([0.2 * np.cos(a), -h, 0.2 * np.sin(a)], 1)              # y down, like Idol's
    hand = np.stack([rng.uniform(0.0, 0.6, 1500), rng.uniform(-0.05, 0.08, 1500), rng.uniform(-0.15, 0.15, 1500)], 1)
    pts = np.concatenate([xyz, hand])
    v = {"x": pts[:, 0], "y": pts[:, 1], "z": pts[:, 2], "opacity": np.full(len(pts), 5.0)}
    centred, _, _ = photo_to_3d._normalise(v)
    body = centred[:n]
    assert abs(np.median(body[:, 0])) < 0.05 and abs(np.median(body[:, 2])) < 0.05
