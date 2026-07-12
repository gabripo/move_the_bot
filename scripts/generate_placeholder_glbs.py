#!/usr/bin/env python3
"""Generate minimal GLB placeholder files for development.

Each GLB contains a simple colored mesh (cube, sphere, cylinder) so the
3D viewer has something to render. Replace with real models for production.
"""

import struct
import json
import math
import os

MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "models", "builtin")


def write_glb(path, vertices, indices, color):
    """Write a minimal valid GLB file with a single mesh."""
    Accessor = {
        "bufferView": 0,
        "componentType": 5126,
        "count": len(vertices) // 3,
        "type": "VEC3",
        "max": [max(vertices[i] for i in range(0, len(vertices), 3))] * 3,
        "min": [min(vertices[i] for i in range(0, len(vertices), 3))] * 3,
    }
    AccessorIndices = {
        "bufferView": 1,
        "componentType": 5123,
        "count": len(indices),
        "type": "SCALAR",
        "max": [max(indices)],
        "min": [min(indices)],
    }

    gltf = {
        "asset": {"version": "2.0", "generator": "placeholder_generator"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{
            "primitives": [{
                "attributes": {"POSITION": 0},
                "indices": 1,
                "material": 0,
            }],
        }],
        "materials": [{
            "pbrMetallicRoughness": {
                "baseColorFactor": [color[0], color[1], color[2], 1.0],
                "metallicFactor": 0.3,
                "roughnessFactor": 0.6,
            },
        }],
        "accessors": [Accessor, AccessorIndices],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(vertices) * 4, "target": 34962},
            {"buffer": 0, "byteOffset": len(vertices) * 4, "byteLength": len(indices) * 2, "target": 34963},
        ],
        "buffers": [{
            "byteLength": len(vertices) * 4 + len(indices) * 2,
        }],
    }

    json_str = json.dumps(gltf, separators=(",", ":"))
    json_padded = json_str + " " * (4 - len(json_str) % 4) if len(json_str) % 4 else json_str
    json_bytes = json_padded.encode("ascii")
    json_pad = (4 - len(json_bytes) % 4) % 4

    bin_data = struct.pack(f"<{len(vertices)}f", *vertices)
    bin_data += struct.pack(f"<{len(indices)}H", *indices)
    bin_pad = (4 - len(bin_data) % 4) % 4
    bin_data += b" " * bin_pad

    tot_len = 12 + 8 + len(json_bytes) + json_pad + 8 + len(bin_data)
    glb = b"glTF"
    glb += struct.pack("<II", 2, tot_len)
    glb += struct.pack("<II", len(json_bytes) + json_pad, 0x4E4F534A)
    glb += json_bytes + b" " * json_pad
    glb += struct.pack("<II", len(bin_data), 0x004E4942)
    glb += bin_data

    with open(path, "wb") as f:
        f.write(glb)
    print(f"  Created {path} ({len(glb)} bytes)")


def make_cube(r=0.05):
    h = r
    vs = [
        -r, -r, -h,  r, -r, -h,  r,  r, -h, -r,  r, -h,
        -r, -r,  h,  r, -r,  h,  r,  r,  h, -r,  r,  h,
    ]
    idxs = [
        0,1,2, 0,2,3, 1,5,6, 1,6,2, 5,4,7, 5,7,6,
        4,0,3, 4,3,7, 3,2,6, 3,6,7, 4,5,1, 4,1,0,
    ]
    return vs, idxs


def make_sphere(radius=0.05, rings=12, sectors=12):
    vs = []
    idxs = []
    for r in range(rings + 1):
        phi = math.pi * r / rings
        for s in range(sectors + 1):
            theta = 2 * math.pi * s / sectors
            vs.append(radius * math.sin(phi) * math.cos(theta))
            vs.append(radius * math.cos(phi))
            vs.append(radius * math.sin(phi) * math.sin(theta))
    for r in range(rings):
        for s in range(sectors):
            cur = r * (sectors + 1) + s
            nxt = cur + sectors + 1
            idxs.extend([cur, nxt, cur + 1, cur + 1, nxt, nxt + 1])
    return vs, idxs


def make_cylinder(radius=0.05, height=0.10, segs=16):
    vs = []
    idxs = []
    h2 = height / 2
    for i in range(segs):
        a = 2 * math.pi * i / segs
        vs.append(radius * math.cos(a))
        vs.append(radius * math.sin(a))
        vs.append(-h2)
    for i in range(segs):
        a = 2 * math.pi * i / segs
        vs.append(radius * math.cos(a))
        vs.append(radius * math.sin(a))
        vs.append(h2)
    for i in range(segs):
        n = (i + 1) % segs
        idxs.extend([i, n, i + segs, n, n + segs, i + segs])
    vs.extend([0, 0, -h2, 0, 0, h2])
    c = 2 * segs
    for i in range(segs):
        n = (i + 1) % segs
        idxs.extend([c, i, n, c + 1, n + segs, i + segs])
    return vs, idxs


def main():
    os.makedirs(MODELS_DIR, exist_ok=True)
    print("Generating placeholder GLB models:")

    vs, idxs = make_cube(0.05)
    write_glb(os.path.join(MODELS_DIR, "apple.glb"), vs, idxs, (0.8, 0.1, 0.1))

    vs, idxs = make_cylinder(0.04, 0.08, 12)
    write_glb(os.path.join(MODELS_DIR, "mug.glb"), vs, idxs, (0.4, 0.2, 0.1))

    vs, idxs = make_cylinder(0.03, 0.12, 12)
    write_glb(os.path.join(MODELS_DIR, "bottle.glb"), vs, idxs, (0.1, 0.6, 0.2))

    vs, idxs = make_cube(0.05)
    write_glb(os.path.join(MODELS_DIR, "cube.glb"), vs, idxs, (0.3, 0.3, 0.8))

    vs, idxs = make_sphere(0.05, 12, 12)
    write_glb(os.path.join(MODELS_DIR, "sphere.glb"), vs, idxs, (0.8, 0.8, 0.2))

    vs, idxs = make_cube(0.15)
    write_glb(os.path.join(MODELS_DIR, "table.glb"), vs, idxs, (0.6, 0.4, 0.2))

    vs, idxs = make_cylinder(0.04, 0.08, 12)
    write_glb(os.path.join(MODELS_DIR, "can.glb"), vs, idxs, (0.8, 0.2, 0.2))

    vs, idxs = make_cylinder(0.04, 0.08, 12)
    write_glb(os.path.join(MODELS_DIR, "cylinder.glb"), vs, idxs, (0.7, 0.7, 0.1))

    print("\nDone. Replace with real GLB models for production.")


if __name__ == "__main__":
    main()
