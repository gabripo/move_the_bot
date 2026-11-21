"""scripts/solid_mug.py: points of a mug, cup or can become a solid, textured model."""
import importlib.util
import json
import struct
import sys
from pathlib import Path

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("solid_mug", SCRIPTS / "solid_mug.py")
solid_mug = importlib.util.module_from_spec(spec)
spec.loader.exec_module(solid_mug)


def mug_points(n=30000, handle=True, seed=3):
    """A mug 0.7 tall, radius 0.3 (y up), red on one side, with a C-shaped handle at -x."""
    rng = np.random.default_rng(seed)
    a = rng.uniform(-np.pi, np.pi, n)
    y = rng.uniform(0, 0.7, n)
    p = np.stack([0.3 * np.cos(a), y, 0.3 * np.sin(a)], 1)
    c = np.where((np.cos(a) > 0.5)[:, None], [0.8, 0.1, 0.1], [0.05, 0.05, 0.05])
    if handle:
        m = n // 6
        t = rng.uniform(-0.5 * np.pi, 0.5 * np.pi, m)
        g = rng.uniform(0, 2 * np.pi, m)
        reach = 0.15 + 0.03 * np.cos(g)
        s = 0.3 + reach * np.cos(t)
        hy = 0.35 + 0.2 * np.sin(t) / np.sin(0.5 * np.pi) + 0.0 * g
        hp = np.stack([-s, hy, 0.04 * np.sin(g)], 1)
        p = np.concatenate([p, hp])
        c = np.concatenate([c, np.tile([0.05, 0.05, 0.05], (m, 1))])
    return p + [0.1, 0, -0.2], c                   # off the origin: the axis is found


def parse(glb: bytes) -> dict:
    assert glb[:4] == b"glTF"
    length = struct.unpack("<I", glb[12:16])[0]
    return json.loads(glb[20:20 + length])


def test_names_worth_trying_as_cylinders():
    assert solid_mug.is_round_name("kaioken mug")
    assert solid_mug.is_round_name("Monster drink")
    assert solid_mug.is_round_name("coke cans")
    assert not solid_mug.is_round_name("stapler")
    assert not solid_mug.is_round_name("canvas")


def test_a_cylinder_fits_and_a_heap_does_not():
    points, _ = mug_points()
    assert solid_mug.fits_cylinder(points)
    assert not solid_mug.fits_cylinder(np.random.default_rng(0).uniform(-0.3, 0.3, (20000, 3)))


def test_a_mug_becomes_a_body_a_rim_and_a_handle():
    points, colours = mug_points()
    doc = parse(solid_mug.solid_glb(points, colours))
    prims = doc["meshes"][0]["primitives"]
    assert [doc["materials"][p["material"]]["name"] for p in prims] == ["print", "plain", "handle"]
    assert doc["images"][0]["mimeType"] == "image/png"
    body = doc["accessors"][prims[0]["attributes"]["POSITION"]]
    assert np.allclose(body["min"], [-0.3, 0, -0.3], atol=0.02)     # the axis at x = z = 0, on y = 0
    assert np.allclose(body["max"], [0.3, 0.7, 0.3], atol=0.02)
    handle = doc["accessors"][prims[2]["attributes"]["POSITION"]]
    assert handle["min"][0] < -0.4                                    # it sticks out at -x


def test_a_can_has_no_handle():
    points, colours = mug_points(handle=False)
    doc = parse(solid_mug.solid_glb(points, colours))
    assert len(doc["meshes"][0]["primitives"]) == 2


def test_a_point_cloud_glb_reads_back(tmp_path):
    sys.path.insert(0, str(SCRIPTS))
    import photo_to_3d
    points, colours = mug_points(handle=False)
    back, srgb = solid_mug.read_points_glb(photo_to_3d.glb_bytes(points.astype(np.float32), colours))
    assert np.allclose(back, points, atol=1e-5)
    assert np.allclose(srgb, colours, atol=0.02)
