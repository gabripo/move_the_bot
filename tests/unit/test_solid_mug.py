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


def can_photos(turn=-90.0, n=4, hand=True, size=400):
    """Cut-out photos of a can 1 tall and 0.4 wide, its label red going round and green going up,
    each photo a `turn` further round; a skin-coloured hand holding it from below."""
    photos = []
    for k in range(n):
        img = np.zeros((size, size, 4), np.uint8)
        top, bottom, xc, half = 70, 330, 200, 52
        for x in range(int(xc - half) + 1, int(xc + half)):
            s = (x - xc) / half
            az = (solid_mug.FACE_CAMERA + k * turn - np.degrees(np.arcsin(s)) + 180) % 360 - 180
            for y in range(top, bottom):
                v = (y - top) / (bottom - top)
                img[y, x] = [int(255 * (az + 180) / 360), int(255 * v), 40, 255]
        if hand:
            img[320:360, 150:250] = [225, 170, 140, 255]      # skin, below and over the bottom
        photos.append(img)
    return photos


def test_a_can_is_wrapped_from_its_photos_the_right_way_round():
    for turn in (-90.0, 90.0):
        glb, aspect, found = solid_mug.wrap_can(can_photos(turn), size=(360, 180))
        assert found == turn
        assert abs(aspect - 104 / 260) < 0.03
        doc = parse(glb)
        assert [m["name"] for m in doc["materials"]] == ["print", "lid", "plain"]
        # The label, unrolled: red grows with the angle round, green with the height down.
        from PIL import Image
        import io
        view = doc["bufferViews"][doc["images"][0]["bufferView"]]
        start = 20 + struct.unpack("<I", glb[12:16])[0] + 8 + view["byteOffset"]
        tex = np.array(Image.open(io.BytesIO(glb[start:start + view["byteLength"]]))).astype(float)
        az = (np.arange(360) + 0.5) - 180
        red = 255 * (az + 180) / 360
        middle = tex[60:120]
        err = np.abs(middle[..., 0] - red[None, :])
        assert np.median(err) < 8, np.median(err)
        assert abs(np.median(tex[30, :, 1]) - 255 * 30 / 180) < 15        # green: the height
        hand = (np.abs(tex[..., :3] - [225, 170, 140]).max(-1) < 20).mean()
        assert hand < 0.01, hand                                           # the hand is not painted on


def test_a_squat_wide_shape_is_not_taken_for_a_can():
    import pytest
    wide = [np.pad(np.full((60, 300, 4), 200, np.uint8), ((170, 170), (50, 50), (0, 0))) for _ in range(2)]
    with pytest.raises(ValueError):
        solid_mug.wrap_can(wide, size=(180, 90))


def test_a_person_kept_behind_the_can_does_not_widen_it():
    photos = can_photos(90.0, hand=False)
    for k in (0, 3):                                     # SAM 2 kept the head and shoulders
        img = photos[k]
        behind = img[..., 3] == 0
        yy, xx = np.mgrid[:400, :400]
        person = ((xx - 200) ** 2 / 90 ** 2 + (yy - 150) ** 2 / 110 ** 2 < 1) | ((yy > 260) & (np.abs(xx - 200) < 170))
        img[behind & person] = [90, 90, 90, 255]
    glb, aspect, turn = solid_mug.wrap_can(photos, size=(360, 180))
    assert abs(aspect - 104 / 260) < 0.04, aspect
