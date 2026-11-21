#!/usr/bin/env python3
"""Turn one photo of an object, such as your own mug, into a 3D model the scene can draw.

    python3 scripts/photo_to_3d.py --image my-mug.jpg --name mug     # runs Idol's public demo
    python3 scripts/photo_to_3d.py --ply my-mug.ply --name mug       # a splat you already have
    python3 scripts/photo_to_3d.py --ply front.ply left.ply back.ply right.ply --name mug
                                     # splats of photos a quarter turn apart, fused (fuse_splats)

Idol (https://speridlabs.com/research/idol, open weights, Apache-2.0 code) turns a single image
into a 3D Gaussian splat, including the sides the picture does not show. This script turns that
splat into coloured points, stands it upright, turns the photographed side towards the camera of
the recording view (?rec) and writes models/local/<name>.glb. That folder is never committed:
see models/local/README.md. Rebuild the images afterwards (./run.sh --rebuild).

A mug, cup or can (by its name) that looks like a cylinder is made solid instead: see
solid_mug.py (needs scipy and Pillow; --points keeps the points). Needs numpy. --image also needs gradio_client (pip install gradio_client); the demo runs on
Hugging Face's shared GPUs, which give a limited daily quota without a Hugging Face login.
"""
from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SH_C0 = 0.28209479177387814           # spherical harmonics, band 0: colour = 0.5 + C0 * f_dc
# Idol's splats look at the photo from +x, with y pointing down (a camera frame). Turning +x by
# this many degrees about the vertical points the photographed side at the recording camera.
FACE_CAMERA_YAW = 147.0
PLY_TYPES = {"float": "f4", "float32": "f4", "double": "f8", "float64": "f8", "uchar": "u1",
             "uint8": "u1", "char": "i1", "int8": "i1", "short": "i2", "ushort": "u2",
             "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4"}


def read_ply(path: Path) -> dict[str, np.ndarray]:
    """The vertex properties of a binary little-endian PLY file (what 3DGS tools write)."""
    return parse_ply(Path(path).read_bytes())


def parse_ply(data: bytes) -> dict[str, np.ndarray]:
    """read_ply() for a PLY file already in memory."""
    end = data.index(b"end_header\n") + len(b"end_header\n")
    header = data[:end].decode("ascii").splitlines()
    if "format binary_little_endian 1.0" not in header:
        raise ValueError("only binary little-endian PLY files are supported")
    count, fields, in_vertex = 0, [], False
    for line in header:
        parts = line.split()
        if parts[:1] == ["element"]:
            in_vertex = parts[1] == "vertex"
            if in_vertex:
                count = int(parts[2])
        elif parts[:1] == ["property"] and in_vertex:
            fields.append((parts[2], "<" + PLY_TYPES[parts[1]]))
    rows = np.frombuffer(data, dtype=np.dtype(fields), count=count, offset=end)
    return {name: rows[name].astype(np.float64) for name, _ in fields}


def splat_to_points(v: dict[str, np.ndarray], min_opacity: float = 0.12,
                    yaw_degrees: float = FACE_CAMERA_YAW) -> tuple[np.ndarray, np.ndarray]:
    """Points (y up, standing on y = 0, footprint centred on x = z = 0) and their sRGB colours."""
    xyz = np.stack([v["x"], v["y"], v["z"]], 1)
    colour = np.clip(0.5 + SH_C0 * np.stack([v["f_dc_0"], v["f_dc_1"], v["f_dc_2"]], 1), 0, 1)
    opacity = 1 / (1 + np.exp(-v["opacity"]))
    size = np.exp(np.stack([v[f"scale_{i}"] for i in range(3)], 1)).max(1)
    keep = (opacity > min_opacity) & (size <= np.percentile(size, 97))    # no faint or huge blobs
    xyz, colour = xyz[keep], colour[keep]
    distance = np.linalg.norm(xyz - np.median(xyz, 0), axis=1)            # no stray points
    near = distance <= np.percentile(distance, 99.7)
    xyz, colour = xyz[near], colour[near]

    xyz[:, 1] *= -1                                                        # camera frame -> y up
    xyz[:, 2] *= -1
    y = xyz[:, 1] - xyz[:, 1].min()
    height = y.max()
    # Centre on what it stands on: the middle of the footprint's extent (a median would be pulled
    # towards the side with more points, such as the photographed one, or miss the centre of a ring).
    footprint = xyz[y < 0.03 * height]
    lo, hi = np.percentile(footprint[:, [0, 2]], 2, axis=0), np.percentile(footprint[:, [0, 2]], 98, axis=0)
    cx, cz = (lo + hi) / 2
    x, z = xyz[:, 0] - cx, xyz[:, 2] - cz
    a = np.radians(yaw_degrees)
    points = np.stack([x * np.cos(a) - z * np.sin(a), y, x * np.sin(a) + z * np.cos(a)], 1)
    return points.astype(np.float32), colour


def ply_bytes(v: dict[str, np.ndarray]) -> bytes:
    """A binary PLY of these vertex properties (float32), as 3DGS tools read it."""
    names = list(v)
    rows = np.zeros(len(v[names[0]]), dtype=[(n, "<f4") for n in names])
    for n in names:
        rows[n] = v[n]
    header = f"ply\nformat binary_little_endian 1.0\nelement vertex {len(rows)}\n"
    header += "".join(f"property float {n}\n" for n in names) + "end_header\n"
    return header.encode() + rows.tobytes()


# ------------------------------------------------------------------ several views of one object
#
# Idol makes a whole object from one photo, inventing the sides it cannot see. With photos from
# several sides (the object turned between them), each one gives a whole object whose
# photographed side is real. fuse_splats() turns them into one frame and keeps every part of the
# surface from the view that saw it. The photographed side of a splat is its +x side (Idol's
# input camera, y pointing down), as splat_to_points() assumes too.

def _normalise(v: dict[str, np.ndarray], min_opacity: float = 0.12):
    """Footprint centred at x = z = 0, base at y = 0, height 1 (y still points down)."""
    xyz = np.stack([v["x"], v["y"], v["z"]], 1)
    opacity = 1 / (1 + np.exp(-v["opacity"]))
    solid = xyz[opacity > min_opacity]
    top, base = solid[:, 1].min(), solid[:, 1].max()
    height = max(base - top, 1e-6)
    foot = solid[solid[:, 1] > base - 0.03 * height]
    lo, hi = np.percentile(foot[:, [0, 2]], 2, axis=0), np.percentile(foot[:, [0, 2]], 98, axis=0)
    centre = np.array([(lo[0] + hi[0]) / 2, base, (lo[1] + hi[1]) / 2])
    return (xyz - centre) / height, height, opacity > min_opacity


def _sample(xyz: np.ndarray, v: dict[str, np.ndarray], keep: np.ndarray, n: int = 3000):
    """A random sample of solid points and their colours, for matching views."""
    idx = np.flatnonzero(keep)
    idx = np.random.default_rng(0).choice(idx, size=min(n, len(idx)), replace=False)
    rgb = np.clip(0.5 + SH_C0 * np.stack([v["f_dc_0"], v["f_dc_1"], v["f_dc_2"]], 1)[idx], 0, 1)
    return xyz[idx].astype(np.float32), rgb.astype(np.float32)


def _turn(xyz: np.ndarray, degrees: float) -> np.ndarray:
    """Turn about the vertical (y) axis, the same way splat_to_points() applies its yaw."""
    a = np.radians(degrees)
    x, z = xyz[..., 0], xyz[..., 2]
    out = xyz.copy()
    out[..., 0], out[..., 2] = x * np.cos(a) - z * np.sin(a), x * np.sin(a) + z * np.cos(a)
    return out


def _azimuth(xyz: np.ndarray) -> np.ndarray:
    return np.degrees(np.arctan2(xyz[..., 2], xyz[..., 0]))


def _nearest(a: np.ndarray, b: np.ndarray):
    """For each point of a: distance to, and index of, its nearest point in b."""
    d = (a * a).sum(1)[:, None] + (b * b).sum(1)[None, :] - 2 * a @ b.T
    i = d.argmin(1)
    return np.sqrt(np.maximum(d[np.arange(len(a)), i], 0)), i


SEEN = 60.0       # degrees either side of the photographed direction that a view really saw
UNSEEN = 0.35     # the colour difference counted where two views saw too little in common


def best_turn(ref_xyz, ref_rgb, xyz, rgb, prior: float | None = None, within: float | None = None) -> float:
    """The angle (degrees) that turns one view onto another (`ref`). Shape and colour both count;
    colour only where both views really saw the surface (their photographed sides overlap), since
    Idol invents what it did not see. With `prior` (the turn the user was asked for) and `within`,
    only turns that far from it are tried: Idol's guesses from different sides differ enough that
    the shape alone is a weak guide. Without them, the whole circle is tried."""
    return _best_turn(ref_xyz, ref_rgb, xyz, rgb, prior, within)[0]


def _best_turn(ref_xyz, ref_rgb, xyz, rgb, prior=None, within=None) -> tuple[float, float]:
    """best_turn(), and how well that turn matches (lower is better)."""
    ref_seen = np.abs(_azimuth(ref_xyz)) < SEEN
    own_seen = np.abs(_azimuth(xyz)) < SEEN

    def cost(angle: float) -> float:
        turned = _turn(xyz, angle)
        there, near_there = _nearest(ref_xyz, turned)
        back, near_back = _nearest(turned, ref_xyz)
        c = (there.mean() + back.mean()) / 2
        # Colour both ways round, so that matching a to b and b to a agree.
        for seen, other_seen, dist, near, colour, other in (
                (own_seen, ref_seen, back, near_back, rgb, ref_rgb),
                (ref_seen, own_seen, there, near_there, ref_rgb, rgb)):
            both = seen & other_seen[near] & (dist < 0.05)
            c += 0.25 * (np.abs(colour[both] - other[near[both]]).mean() if both.sum() >= 30 else UNSEEN)
        if prior is not None and within is None:
            off = min(abs((angle - prior + 180) % 360 - 180), abs((angle + prior + 180) % 360 - 180))
            c += 0.002 * off / 90
        return float(c)

    if prior is not None and within is not None:
        candidates = np.arange(prior - within, prior + within + 0.5, 5.0)
    else:
        candidates = np.arange(-180, 180, 5.0)
    coarse = min(candidates, key=cost)
    best = min(np.arange(coarse - 5, coarse + 5.5, 1.0), key=cost)
    return float(best), cost(best)


def fuse_splats(views: list[dict[str, np.ndarray]], step: float | None = None, within: float = 30.0
                ) -> tuple[dict[str, np.ndarray], list[float]]:
    """One splat from several views of the same object. The first view sets the frame (its
    photographed side stays at +x); `step` is the turn between photos the user was asked for
    (degrees, either way round: the photos decide which), and each real turn is looked for within
    `within` degrees of it. When the photos go all the way round, the turns must add up to one
    full turn, and the difference is shared out (loop closure). Without `step`, every turn is
    looked for all round the circle. Returns the splat (height 1, y down, like Idol's) and each
    view's angle (positive: turned clockwise, seen from above)."""
    normal = [_normalise(v) for v in views]
    samples = [_sample(xyz, v, keep) for v, (xyz, _, keep) in zip(views, normal)]
    # Each view against the one before it: neighbours share real surface, opposite sides do not.
    n = len(views)
    if step is None:
        turns = [best_turn(*samples[k - 1], *samples[k]) for k in range(1, n)]
    else:
        # Which way round the object was turned: whichever matches better over all the photos.
        tries = []
        for prior in (step, -step):
            found = [_best_turn(*samples[k - 1], *samples[k], prior, within) for k in range(1, n)]
            full_circle = n > 2 and abs(abs(n * step) - 360) < 1
            if full_circle:
                found.append(_best_turn(*samples[-1], *samples[0], prior, within))
            turns = [t for t, _ in found]
            if full_circle:   # the turns make one full turn: share out the difference
                error = sum(turns) - np.sign(prior) * 360
                turns = [t - error / n for t in turns[:-1]]
            tries.append((sum(c for _, c in found), turns))
        turns = min(tries, key=lambda t: t[0])[1]
    angles = [0.0]
    for turn in turns:
        angles.append(float((angles[-1] + turn + 180) % 360 - 180))

    keys = [k for k in views[0] if k in ("x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
                                           "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3")]
    parts = {k: [] for k in keys}
    for k, (v, (xyz, height, _), angle) in enumerate(zip(views, normal, angles)):
        xyz = _turn(xyz, angle)
        # Every point belongs to the view whose photographed side is closest to it.
        azimuth = np.degrees(np.arctan2(xyz[:, 2], xyz[:, 0]))
        gaps = np.stack([np.abs((azimuth - a + 180) % 360 - 180) for a in angles], 1)
        mine = gaps.argmin(1) == k
        near_axis = np.hypot(xyz[:, 0], xyz[:, 2]) < 0.05       # top and bottom: from the first view
        mine = (mine & ~near_axis) | (near_axis & (k == 0))
        for name in keys:
            if name in ("x", "y", "z"):
                parts[name].append(xyz[mine, "xyz".index(name)])
            elif name.startswith("scale_"):
                parts[name].append(v[name][mine] - np.log(height))   # log scales follow the size
            else:
                parts[name].append(v[name][mine])
        if "rot_0" in keys:
            # Turn each Gaussian too. _turn() is a rotation by -angle about y (right-handed), so
            # q' = q_turn * q with q_turn = (cos(angle/2), 0, -sin(angle/2), 0), in 3DGS's (w, x, y, z).
            h = np.radians(angle) / 2
            w, x, y, z = (parts[f"rot_{i}"][-1] for i in range(4))
            c, s = np.cos(h), np.sin(h)
            parts["rot_0"][-1], parts["rot_1"][-1], parts["rot_2"][-1], parts["rot_3"][-1] = (
                c * w + s * y, c * x - s * z, c * y - s * w, c * z + s * x)
    return {k: np.concatenate(p) for k, p in parts.items()}, angles


def real_size(points: np.ndarray, height: float) -> tuple[float, float, float]:
    """Width, depth and height in metres of an object `height` metres tall (a single photo does
    not tell how big something is). In the robot's frame: x = points' x, y = -z, z = y."""
    extent = points.max(0) - points.min(0)
    scale = height / max(float(extent[1]), 1e-6)
    return float(extent[0] * scale), float(extent[2] * scale), float(height)


def write_glb(path: Path, points: np.ndarray, srgb: np.ndarray) -> None:
    """Write glb_bytes() to a file."""
    path.write_bytes(glb_bytes(points, srgb))


def glb_bytes(points: np.ndarray, srgb: np.ndarray) -> bytes:
    """A glTF binary with one point cloud (mode 0) and its vertex colours."""
    linear = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
    rgba = np.concatenate([np.round(linear * 255), np.full((len(points), 1), 255)], 1).astype(np.uint8)
    positions = np.ascontiguousarray(points, dtype="<f4").tobytes()
    colours = np.ascontiguousarray(rgba).tobytes()
    blob = positions + colours
    doc = {
        "asset": {"version": "2.0", "generator": "move_the_bot photo_to_3d.py"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"mode": 0, "attributes": {"POSITION": 0, "COLOR_0": 1}}]}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
                        {"buffer": 0, "byteOffset": len(positions), "byteLength": len(colours)}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(points), "type": "VEC3",
             "min": points.min(0).tolist(), "max": points.max(0).tolist()},
            {"bufferView": 1, "componentType": 5121, "normalized": True, "count": len(points),
             "type": "VEC4"},
        ],
    }
    text = json.dumps(doc, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    blob += b"\0" * (-len(blob) % 4)
    chunks = struct.pack("<II", len(text), 0x4E4F534A) + text + struct.pack("<II", len(blob), 0x004E4942) + blob
    return struct.pack("<III", 0x46546C67, 2, 12 + len(chunks)) + chunks


def run_idol(image: Path, gaussians: str, seed: int, folder: Path) -> Path:
    """Run Idol's public demo on Hugging Face and return the splat it made."""
    try:
        from gradio_client import Client, handle_file
    except ImportError:
        sys.exit("--image needs gradio_client: pip install gradio_client")
    print("Asking Idol's demo on Hugging Face (about 30 s, longer when it has to start)…")
    result, _, _ = Client("speridlabs/idol", verbose=False).predict(
        handle_file(str(image)), "Real photo", 50, 3.0, 3.0, seed, False, gaussians, api_name="/run")
    target = folder / f"{image.stem}.ply"
    shutil.copy(result, target)
    return target


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", type=Path, help="a photo of the object, ideally on a plain background")
    source.add_argument("--ply", type=Path, nargs="+",
                        help="a Gaussian splat (.ply) made by Idol or a similar model; several: photos "
                             "of the object turned the same way by --step degrees each time, fused")
    p.add_argument("--name", required=True, help="the object it replaces, e.g. mug (models/local/<name>.glb)")
    p.add_argument("--gaussians", default="262,144",
                   choices=["65,536", "131,072", "262,144", "524,288", "1,048,576"], help="detail (with --image)")
    p.add_argument("--seed", type=int, default=42, help="same seed, same object (with --image)")
    p.add_argument("--yaw", type=float, default=FACE_CAMERA_YAW,
                   help="degrees to turn the photographed side, default: towards the recording camera")
    p.add_argument("--min-opacity", type=float, default=0.12, help="drop fainter Gaussians")
    p.add_argument("--step", type=float, default=None,
                   help="with several --ply: the turn between photos (default: one full turn in all)")
    p.add_argument("--points", action="store_true",
                   help="keep the points: no solid model, even for a mug, cup or can (solid_mug.py)")
    args = p.parse_args()

    out = ROOT / "models" / "local"
    if args.ply and len(args.ply) > 1:
        step = args.step or 360 / len(args.ply)
        splat, angles = fuse_splats([read_ply(f) for f in args.ply], step=step)
        print("Fused the photos, found at " + ", ".join(f"{a:.0f}°" for a in angles))
    else:
        splat = read_ply(args.ply[0] if args.ply else run_idol(args.image, args.gaussians, args.seed, out))
    points, colours = splat_to_points(splat, args.min_opacity, args.yaw)
    target = out / f"{args.name.lower().replace(' ', '_')}.glb"
    solid = None
    if not args.points:
        sys.path.insert(0, str(Path(__file__).parent))
        import solid_mug                          # round things become solid; needs scipy and Pillow
        if solid_mug.is_round_name(args.name) and solid_mug.fits_cylinder(points):
            solid = solid_mug.solid_glb(points, colours)
    if solid:
        target.write_bytes(solid)
        what = "a solid model (--points keeps the points)"
    else:
        write_glb(target, points, colours)
        what = f"{len(points):,} points"
    print(f"Wrote {target.relative_to(ROOT)}: {what}. Rebuild with ./run.sh --rebuild "
          f"and create a {args.name} to see it.")


if __name__ == "__main__":
    main()
