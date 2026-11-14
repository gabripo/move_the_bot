#!/usr/bin/env python3
"""Generate the small 3D models in models/builtin/ (apple, mug, bottle...).

The sizes come from the object catalogue in ros/move_the_bot/move_the_bot/world.py, so what you
see in the browser is what the robot plans with. Run after changing the catalogue:

    pip install trimesh numpy
    python3 scripts/make_models.py
"""
import math
import sys
from pathlib import Path

import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ros" / "move_the_bot"))
from move_the_bot.world import CATALOGUE  # noqa: E402

OUT = ROOT / "models" / "builtin"


def rgb(hex_colour):
    h = hex_colour.lstrip("#")
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)] + [1.0]


def paint(mesh, colour, roughness=0.55, metallic=0.0):
    mesh.visual = trimesh.visual.TextureVisuals(
        material=PBRMaterial(baseColorFactor=rgb(colour), roughnessFactor=roughness, metallicFactor=metallic))
    return mesh


def cylinder(radius, height, z, colour, sections=48, **kw):
    m = trimesh.creation.cylinder(radius=radius, height=height, sections=sections)
    m.apply_translation([0, 0, z])
    return paint(m, colour, **kw)


def sphere(radius, colour, squash=1.0, **kw):
    m = trimesh.creation.icosphere(subdivisions=4, radius=radius)
    m.apply_scale([1, 1, squash])
    return paint(m, colour, **kw)


def build(kind, spec):
    sx, sy, sz = spec["size"]
    colour = spec["color"]
    r = min(sx, sy) / 2
    if kind == "apple":
        body = sphere(r, colour, squash=sz / (2 * r) * 0.92, roughness=0.35)
        stem = cylinder(0.0022, 0.014, sz / 2 - 0.004, "#5d4037")
        leaf = sphere(0.008, "#43a047", squash=0.25)
        leaf.apply_translation([0.008, 0, sz / 2 + 0.001])
        return [body, stem, leaf]
    if kind == "orange":
        return [sphere(r, colour, roughness=0.7), cylinder(0.004, 0.003, sz / 2 - 0.001, "#2e7d32")]
    if kind == "ball":
        band = trimesh.creation.torus(major_radius=r * 0.985, minor_radius=r * 0.06)
        return [sphere(r, colour, roughness=0.4), paint(band, "#fafafa")]
    if kind == "cube":
        return [paint(trimesh.creation.box(extents=[sx, sy, sz]), colour)]
    if kind == "can":
        return [
            cylinder(r, sz * 0.96, 0, colour, roughness=0.3, metallic=0.8),
            cylinder(r * 1.002, sz * 0.5, 0, "#d32f2f", roughness=0.4, metallic=0.3),
            cylinder(r * 0.93, sz, 0, "#cfd8dc", roughness=0.3, metallic=0.9),
        ]
    if kind == "mug":
        rb = r * 0.82                      # leave room for the handle inside the footprint
        wall = trimesh.creation.annulus(r_min=rb * 0.86, r_max=rb, height=sz, sections=48)
        bottom = cylinder(rb * 0.99, 0.006, -sz / 2 + 0.003, colour)
        coffee = cylinder(rb * 0.87, 0.002, sz / 2 - 0.012, "#4e342e")
        handle = trimesh.creation.torus(major_radius=sz * 0.24, minor_radius=0.0045)
        handle.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [1, 0, 0]))
        handle.apply_translation([rb + sz * 0.10, 0, 0])
        return [paint(wall, colour, roughness=0.3), bottom, coffee, paint(handle, colour, roughness=0.3)]
    if kind == "bottle":
        body_h, neck_h = sz * 0.62, sz * 0.2
        shoulder = trimesh.creation.cone(radius=r, height=sz * 0.14, sections=48)
        shoulder.apply_translation([0, 0, -sz / 2 + body_h])
        return [
            cylinder(r, body_h, -sz / 2 + body_h / 2, colour, roughness=0.2),
            paint(shoulder, colour, roughness=0.2),
            cylinder(r * 0.36, neck_h, -sz / 2 + body_h + sz * 0.08 + neck_h / 2, colour, roughness=0.2),
            cylinder(r * 0.42, sz * 0.07, sz / 2 - sz * 0.035, "#eceff1"),
            cylinder(r * 1.004, body_h * 0.4, -sz / 2 + body_h * 0.5, "#e0f2f1", roughness=0.6),
        ]
    return [cylinder(r, sz, 0, colour)]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    to_y_up = trimesh.transformations.rotation_matrix(-math.pi / 2, [1, 0, 0])   # glTF is y-up
    for kind, spec in CATALOGUE.items():
        scene = trimesh.Scene()
        for i, part in enumerate(build(kind, spec)):
            part.apply_transform(to_y_up)
            scene.add_geometry(part, node_name=f"{kind}_{i}")
        path = OUT / f"{kind}.glb"
        path.write_bytes(scene.export(file_type="glb"))
        size = np.ptp(scene.bounds, axis=0)
        print(f"{path.name:14s} {path.stat().st_size / 1024:6.1f} kB  size {size.round(3)}")


if __name__ == "__main__":
    main()
