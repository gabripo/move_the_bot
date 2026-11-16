#!/usr/bin/env python3
"""Turn one photo of an object, such as your own mug, into a 3D model the scene can draw.

    python3 scripts/photo_to_3d.py --image my-mug.jpg --name mug     # runs Idol's public demo
    python3 scripts/photo_to_3d.py --ply my-mug.ply --name mug       # a splat you already have

Idol (https://speridlabs.com/research/idol, open weights, Apache-2.0 code) turns a single image
into a 3D Gaussian splat, including the sides the picture does not show. This script turns that
splat into coloured points, stands it upright, turns the photographed side towards the camera of
the recording view (?rec) and writes models/local/<name>.glb. That folder is never committed:
see models/local/README.md. Rebuild the images afterwards (./run.sh --rebuild).

Needs numpy. --image also needs gradio_client (pip install gradio_client); the demo runs on
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
    data = path.read_bytes()
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


def write_glb(path: Path, points: np.ndarray, srgb: np.ndarray) -> None:
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
    path.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(chunks)) + chunks)


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
    source.add_argument("--ply", type=Path, help="a Gaussian splat (.ply) made by Idol or a similar model")
    p.add_argument("--name", required=True, help="the object it replaces, e.g. mug (models/local/<name>.glb)")
    p.add_argument("--gaussians", default="262,144",
                   choices=["65,536", "131,072", "262,144", "524,288", "1,048,576"], help="detail (with --image)")
    p.add_argument("--seed", type=int, default=42, help="same seed, same object (with --image)")
    p.add_argument("--yaw", type=float, default=FACE_CAMERA_YAW,
                   help="degrees to turn the photographed side, default: towards the recording camera")
    p.add_argument("--min-opacity", type=float, default=0.12, help="drop fainter Gaussians")
    args = p.parse_args()

    out = ROOT / "models" / "local"
    ply = args.ply or run_idol(args.image, args.gaussians, args.seed, out)
    points, colours = splat_to_points(read_ply(ply), args.min_opacity, args.yaw)
    target = out / f"{args.name.lower().replace(' ', '_')}.glb"
    write_glb(target, points, colours)
    print(f"Wrote {target.relative_to(ROOT)}: {len(points):,} points. Rebuild with ./run.sh --rebuild "
          f"and create a {args.name} to see it.")


if __name__ == "__main__":
    main()
