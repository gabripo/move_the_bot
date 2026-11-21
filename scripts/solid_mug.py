"""Turn a point cloud of a mug, cup or can into a solid model: a cylinder wearing the object's
print, a rim, an inside, a bottom and, when there is one, a handle fitted to its points.

Idol (image to 3D) makes Gaussian splats, which photo_to_3d.py turns into coloured points. Seen up
close those are scattered dots, with gaps where the photos did not show the object. For round
things a much better model is known in advance: a cylinder. Its radius and height come from the
points, its texture is the points unrolled around the axis (the side no photo saw is the object's
own dark colour), and a handle is a tube following the points that stick out.

  python3 scripts/solid_mug.py models/local/mug.glb              # replaces it (a backup is kept)
  python3 scripts/solid_mug.py points.glb -o models/local/mug.glb

The scanner (docker/scan_server.py) does this by itself for objects named like a mug, cup, can or
drink, when the points do look like a cylinder (fits_cylinder); otherwise it keeps the points.
Needs numpy, scipy and Pillow.
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import struct
import sys
from pathlib import Path

import numpy as np

# Object names that are worth trying as a cylinder (with or without a handle).
ROUND_WORDS = ("mug", "cup", "can", "tin", "drink", "soda", "cola", "beer", "monster", "red bull",
               "energy", "glass", "jar", "candle")

RADIUS = 0.29        # the thresholds below were tuned on a mug of this radius: points are scaled to it
TEXTURE = (2048, 1024)
_LUM = np.array([0.2126, 0.7152, 0.0722])


def _has_word(name: str, words) -> bool:
    text = " " + " ".join(name.lower().replace("_", " ").split()) + " "
    return any(f" {w} " in text or f" {w}s " in text for w in words)


def is_round_name(name: str) -> bool:
    """True for names like 'kaioken mug', 'monster drink', 'coke can'."""
    return _has_word(name, ROUND_WORDS)


# Cans and the like: no handle, the same width from top to bottom. Their photos are wrapped
# around a cylinder (wrap_can) instead of going through Idol.
CAN_WORDS = ("can", "tin", "drink", "soda", "cola", "coke", "pepsi", "beer", "monster", "red bull",
             "energy drink", "sprite", "fanta")


def is_can_name(name: str) -> bool:
    """True for 'monster', 'monster drink', 'coke can'; not for a mug or a bottle (a neck)."""
    return _has_word(name, CAN_WORDS)


def srgb_to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


# ----------------------------------------------------------------------------- the fit

def _axis(p: np.ndarray, top: float) -> tuple[float, float, float]:
    """Centre (x, z) and radius of the rim: an algebraic circle fit to the highest points."""
    rim = p[p[:, 1] > top - 0.045 * top]
    a = np.c_[rim[:, 0], rim[:, 2], np.ones(len(rim))]
    b = rim[:, 0] ** 2 + rim[:, 2] ** 2
    (cx, cz, k), *_ = np.linalg.lstsq(a, b, rcond=None)
    cx, cz = cx / 2, cz / 2
    return float(cx), float(cz), float(np.sqrt(max(k + cx ** 2 + cz ** 2, 1e-12)))


def fits_cylinder(points: np.ndarray) -> bool:
    """Whether these points (y up) look like a cylinder standing up: most of the points around the
    middle of the height lie near one radius, and the radius is the same low and high."""
    p = np.asarray(points, dtype=np.float64)
    if len(p) < 2000:
        return False
    p = p - [0, p[:, 1].min(), 0]
    top = np.percentile(p[:, 1], 99.7)
    cx, cz, r0 = _axis(p, top)
    r = np.hypot(p[:, 0] - cx, p[:, 2] - cz)
    y = p[:, 1] / top
    band = (y > 0.2) & (y < 0.8)
    if band.sum() < 500 or not 0.1 < r0 / top < 2.5:
        return False
    on = band & (r > 0.8 * r0) & (r < 1.12 * r0)
    lo = np.median(r[on & (y < 0.45)]) if (on & (y < 0.45)).sum() > 50 else 0
    hi = np.median(r[on & (y > 0.55)]) if (on & (y > 0.55)).sum() > 50 else 0
    straight = lo > 0 and hi > 0 and abs(lo - hi) < 0.15 * r0
    return bool(on.sum() > 0.6 * band.sum() and straight)


def solid_glb(points: np.ndarray, srgb: np.ndarray) -> bytes:
    """A glTF binary of the solid object, standing on y = 0, its axis at x = z = 0, the size of
    the points. `srgb` are the points' colours (0..1)."""
    from PIL import Image
    from scipy import ndimage

    p = np.asarray(points, dtype=np.float64).copy()
    c = srgb_to_linear(np.clip(np.asarray(srgb, dtype=np.float64)[:, :3], 0, 1))
    p[:, 1] -= p[:, 1].min()
    top = np.percentile(p[:, 1], 99.7)
    cx, cz, r0 = _axis(p, top)
    unit = RADIUS / r0                       # work at the tuned size, scale back at the end
    p = (p - [cx, 0, cz]) * unit
    H = top * unit
    r = np.hypot(p[:, 0], p[:, 2])
    ang = np.arctan2(p[:, 2], p[:, 0])
    mid = (p[:, 1] > 0.15 * H) & (p[:, 1] < 0.85 * H)
    R = float(np.percentile(r[mid & (np.abs(r - RADIUS) < 0.06)], 80))

    # --- the print: the points on the outer wall, unrolled around the axis
    W, Ht = TEXTURE
    wall = (r > R - 0.03) & (r < R + 0.022) & (p[:, 1] > 0.005) & (p[:, 1] < H - 0.004)
    u = ((ang[wall] + np.pi) / (2 * np.pi) * W).astype(int) % W
    v = np.clip(((1 - p[wall, 1] / H) * (Ht - 1)).astype(int), 0, Ht - 1)
    acc, cnt, raw = np.zeros((Ht, W, 3)), np.zeros((Ht, W)), np.zeros((Ht, W))
    weight = np.exp((r[wall] - R) / 0.01)                # the outermost points win
    np.add.at(acc, (v, u), c[wall] * weight[:, None])
    np.add.at(cnt, (v, u), weight)
    np.add.at(raw, (v, u), 1)
    # Only where the points are dense: lone points (highlights, strays) would become blots.
    density = ndimage.gaussian_filter(raw, 8, mode="wrap")
    dense = density > 0.25 * np.percentile(density[density > 0], 90) if (density > 0).any() else density > 0
    dense = ndimage.binary_opening(dense, iterations=4)
    # Each point spreads over about the area it covers there: a mug seen from the front has its
    # points packed on one side, a can seen from four sides spreads as many all the way round.
    blur = float(np.clip(0.8 * np.sqrt(max(dense.sum(), 1) / max(wall.sum(), 1)), 1.5, 6.0))
    acc = np.stack([ndimage.gaussian_filter(acc[..., i], blur, mode="wrap") for i in range(3)], -1)
    cnt = ndimage.gaussian_filter(cnt, blur, mode="wrap")
    have = (cnt > 0.15 * np.percentile(cnt[dense], 50)) & dense if dense.any() else dense
    islands, n = ndimage.label(have)
    if n:
        sizes = ndimage.sum(have, islands, range(1, n + 1))
        have &= np.isin(islands, 1 + np.flatnonzero(sizes > 20000 * W * Ht / (2048 * 1024)))
    image = np.where(have[..., None], acc / np.maximum(cnt, 1e-9)[..., None], 0)
    lum = c @ _LUM
    base = 0.6 * np.median(c[lum <= np.median(lum)], axis=0)    # dark: the points catch highlights
    if have.any():
        dist, (iy, ix) = ndimage.distance_transform_edt(~have, return_indices=True)
        t = np.clip(dist / 10.0, 0, 1)[..., None]                 # a short fade into the base colour
        image = np.where(have[..., None], image, image[iy, ix] * (1 - t) + base * t)
    else:
        image[:] = base
    png = io.BytesIO()
    Image.fromarray((linear_to_srgb(image) * 255).round().astype(np.uint8)).save(png, "PNG", optimize=True)

    # --- the body
    N, rows = 128, 33
    a = np.linspace(-np.pi, np.pi, N + 1)
    ring = np.stack([np.cos(a), np.zeros_like(a), np.sin(a)], 1)
    ys = np.linspace(0, H, rows)
    body_p = np.concatenate([ring * R + [0, y, 0] for y in ys])
    body_n = np.tile(ring, (rows, 1))
    body_uv = np.concatenate([np.stack([np.arange(N + 1) / N, np.full(N + 1, 1 - y / H)], 1) for y in ys])
    body_f = np.concatenate([_strip(i * (N + 1), (i + 1) * (N + 1), N) for i in range(rows - 1)])

    th = 0.035 * R / RADIUS                       # the wall's thickness
    Ri, floor = R - th, 0.08 * H
    parts = [  # (positions, normals) of each ring of the plain parts, joined in pairs below
        (ring * R + [0, H, 0], np.tile([0, 1.0, 0], (N + 1, 1))),        # rim, outside
        (ring * Ri + [0, H, 0], np.tile([0, 1.0, 0], (N + 1, 1))),       # rim, inside
        (ring * Ri + [0, H, 0], -ring),                                    # inner wall, top
        (ring * Ri + [0, floor, 0], -ring),                                # inner wall, bottom
    ]
    plain_p = np.concatenate([q for q, _ in parts])
    plain_n = np.concatenate([n for _, n in parts])
    plain_f = [_strip(0, N + 1, N), _strip(2 * (N + 1), 3 * (N + 1), N)]
    for y, up in ((floor, 1.0), (0.0, -1.0)):                             # inner floor, bottom
        start = len(plain_p)
        plain_p = np.concatenate([plain_p, ring * (Ri if up > 0 else R) + [0, y, 0], [[0, y, 0]]])
        plain_n = np.concatenate([plain_n, np.tile([0, up, 0], (N + 2, 1))])
        plain_f.append(np.array([[start + N + 1, start + i, start + i + 1] for i in range(N)]))
    plain_f = np.concatenate(plain_f)

    primitives = [(body_p, body_n, body_uv, body_f, "print"), (plain_p, plain_n, None, plain_f, "plain")]
    handle = _handle(p, c, r, ang, R, H, th)
    if handle is not None:
        primitives.append((*handle[:2], None, handle[2], "handle"))
        handle_colour = np.minimum(handle[3], base)
    else:
        handle_colour = base

    scale = 1 / unit
    out = []
    for pos, nrm, uv, faces, material in primitives:
        out.append((pos * scale, nrm, uv, _wind(pos, nrm, faces), material))
    return _glb(out, png.getvalue(), {"plain": base * 1.1, "handle": handle_colour})


def _strip(i0: int, i1: int, n: int) -> np.ndarray:
    """Two triangles per segment between two rings of n + 1 vertices."""
    i = np.arange(n)
    return np.concatenate([np.stack([i0 + i, i1 + i, i0 + i + 1], 1), np.stack([i0 + i + 1, i1 + i, i1 + i + 1], 1)])


def _wind(pos: np.ndarray, nrm: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Each triangle wound counter-clockwise seen from where its vertices' normals point."""
    a, b, c = pos[faces[:, 0]], pos[faces[:, 1]], pos[faces[:, 2]]
    flip = (np.cross(b - a, c - a) * nrm[faces].sum(1)).sum(1) < 0
    faces = faces.copy()
    faces[flip] = faces[flip][:, [0, 2, 1]]
    return faces


def _handle(p, c, r, ang, R, H, th):
    """A tube through the points outside the wall, from the wall and back into it: (positions,
    normals, faces, colour) or None when there is no handle (a can)."""
    from scipy import ndimage

    out = (r > R + 0.025) & (p[:, 1] > 0.02 * H) & (p[:, 1] < H)
    if out.sum() < max(300, 0.02 * len(p)):
        return None
    # The largest connected lump of them (a stray piece is not the handle): 2 cm voxels.
    q = p[out]
    cell = np.floor((q - q.min(0)) / 0.02).astype(int)
    grid = np.zeros(cell.max(0) + 1, bool)
    grid[tuple(cell.T)] = True
    labels, n = ndimage.label(grid, structure=np.ones((3, 3, 3)))
    lump = labels[tuple(cell.T)]
    keep = lump == np.bincount(lump)[1:].argmax() + 1
    if keep.sum() < 300:
        return None
    hp, hc = q[keep], c[out][keep]
    a_out = ang[out][keep]
    ha = np.arctan2(np.median(np.sin(a_out)), np.median(np.cos(a_out)))
    outward, side = np.array([np.cos(ha), 0, np.sin(ha)]), np.array([-np.sin(ha), 0, np.cos(ha)])
    s, t, y = hp @ outward, hp @ side, hp[:, 1]
    yc = (np.percentile(y, 2) + np.percentile(y, 98)) / 2
    phi = np.arctan2(y - yc, s - R)
    arc = []
    for theta in np.linspace(-0.49 * np.pi, 0.49 * np.pi, 25):
        near = np.abs(np.angle(np.exp(1j * (phi - theta)))) < np.pi / 24
        if near.sum() >= 15:
            d = np.hypot(s[near] - R, y[near] - yc)
            arc.append((theta, np.median(d), np.median(t[near]), (np.percentile(d, 90) - np.percentile(d, 10)) / 2))
    if len(arc) < 8:
        return None
    arc = np.array(arc)
    reach = ndimage.uniform_filter1d(arc[:, 1], 5, mode="nearest")
    across = ndimage.uniform_filter1d(arc[:, 2], 5, mode="nearest")
    tube = float(np.clip(np.median(arc[:, 3]), 0.02, 0.045))
    width = float(np.clip((np.percentile(t, 95) - np.percentile(t, 5)) / 2, tube, 0.06))
    path = np.array([[R + d * np.cos(a), yc + d * np.sin(a), k] for a, d, k in zip(arc[:, 0], reach, across)])
    path = np.concatenate([[[R - 0.6 * th, path[0, 1], path[0, 2]]], path, [[R - 0.6 * th, path[-1, 1], path[-1, 2]]]])
    length = np.r_[0, np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))]
    steps = np.linspace(0, length[-1], 80)
    path = np.stack([ndimage.gaussian_filter1d(np.interp(steps, length, path[:, i]), 2, mode="nearest") for i in range(3)], 1)
    M = 20
    g = 2 * np.pi * np.arange(M) / M
    pos, nrm = [], []
    for i, centre in enumerate(path):                 # (s, y, t): out from the axis, up, sideways
        tangent = path[min(i + 1, len(path) - 1)] - path[max(i - 1, 0)]
        tangent /= np.linalg.norm(tangent)
        across_dir = np.array([0, 0, 1.0])
        in_plane = np.cross(tangent, across_dir)
        in_plane /= np.linalg.norm(in_plane)
        for gj in g:
            pos.append(centre + in_plane * tube * np.cos(gj) + across_dir * width * np.sin(gj))
            n = in_plane * np.cos(gj) / tube + across_dir * np.sin(gj) / width
            nrm.append(n / np.linalg.norm(n))
    to_world = np.stack([outward, [0, 1.0, 0], side])          # rows: where s, y, t point
    pos, nrm = np.array(pos) @ to_world, np.array(nrm) @ to_world
    faces = []
    for i in range(len(path) - 1):
        for j in range(M):
            a0, a1 = i * M + j, i * M + (j + 1) % M
            faces += [[a0, a1, a0 + M], [a1, a1 + M, a0 + M]]
    lum = hc @ _LUM
    return pos, nrm, np.array(faces), np.median(hc[lum <= np.median(lum)], axis=0)


# ----------------------------------------------------------------------------- a can, from photos
#
# A can is a cylinder: all a photo has to tell is its proportions and its label. Each photo, cut
# out (RGBA), shows the can's front as a rectangle; a column of it at s (-1 left .. 1 right of the
# axis) shows the surface at the angle asin(s) from the photo's direction. So the photos, a
# quarter turn apart, are unrolled side by side; where two overlap, the one seeing it more
# head-on counts more. Hands (their landmarks, and skin colours) do not count: the other photos,
# or the can's own colour, fill in behind them.

FACE_CAMERA = 147.0      # degrees: where the first photo's side faces (photo_to_3d.FACE_CAMERA_YAW)


def _can_frame(alpha: np.ndarray):
    """The can's rectangle in a cut-out: (middle x, half width, top row, bottom row), in pixels.
    Rows as wide as the body around the middle of its height; hands under or over it are not."""
    rows = np.flatnonzero(alpha.any(1))
    if len(rows) < 20:
        raise ValueError("no object in the cut-out")
    left = np.array([np.argmax(r) if r.any() else -1 for r in alpha])
    right = np.array([len(r) - 1 - np.argmax(r[::-1]) if r.any() else -1 for r in alpha])
    width = np.where(left >= 0, right - left, 0)
    lo, hi = rows[0], rows[-1]
    band = np.arange(int(lo + 0.35 * (hi - lo)), int(lo + 0.65 * (hi - lo)) + 1)
    w0 = np.median(width[band])
    l0, r0 = np.median(left[band]), np.median(right[band])
    body = (np.abs(width - w0) < 0.1 * w0) & (np.abs(left - l0) < 0.08 * w0) & (np.abs(right - r0) < 0.08 * w0)
    # the run of body rows around the middle, allowing short gaps (a finger across it)
    middle = int(band[len(band) // 2])
    top = bottom = middle
    gap = max(3, int(0.04 * (hi - lo)))
    while top - 1 >= lo and body[max(lo, top - gap):top].any():
        top -= 1
    while bottom + 1 <= hi and body[bottom + 1:bottom + 1 + gap].any():
        bottom += 1
    if bottom - top < 0.2 * (hi - lo) or w0 < 10:
        raise ValueError("no can shape in the cut-out")
    return (l0 + r0) / 2, max(w0 / 2, 1.0), int(top), int(bottom)


def _skin(rgb: np.ndarray) -> np.ndarray:
    """Skin colours (YCrCb ranges), 0..255 RGB."""
    r, g, b = rgb[..., 0].astype(float), rgb[..., 1].astype(float), rgb[..., 2].astype(float)
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cr, cb = (r - y) * 0.713 + 128, (b - y) * 0.564 + 128
    return (cr > 138) & (cr < 175) & (cb > 85) & (cb < 128) & (y > 60)


def _hands_mask(hands, w: int, h: int) -> np.ndarray:
    from PIL import Image, ImageDraw
    canvas = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(canvas)
    for hand in hands or []:
        pts = np.asarray(hand, dtype=float).reshape(-1, 2) * [w, h]
        if len(pts) < 5:
            continue
        middle = pts.mean(0)
        angle = np.arctan2(*(pts - middle).T[::-1])
        ring = pts[np.argsort(angle)]                           # a star-shaped outline is enough
        draw.polygon([tuple(p) for p in middle + 1.3 * (ring - middle)], fill=255)
    return np.array(canvas) > 0


def _unroll(cut: np.ndarray, hands, direction: float, W: int, Ht: int):
    """One photo on the texture: (colours, weights) for a photo facing `direction` degrees."""
    from scipy import ndimage
    rgb, alpha = cut[..., :3], cut[..., 3] > 127
    h, w = alpha.shape
    can = alpha & ~_hands_mask(hands, w, h)
    xc, half, top, bottom = _can_frame(can)
    # Skin: a hand reaches out of the can's outline, a skin-coloured print does not. Rows at the
    # ends that are mostly such skin (a hand under it, as wide as the can) are not the can.
    skin = _skin(rgb) & alpha
    parts, n = ndimage.label(skin)
    if n:
        inside = np.zeros_like(alpha)
        inside[top:bottom + 1, int(xc - half) + 2:int(xc + half) - 1] = True
        out = np.unique(parts[skin & ~inside])
        skin = np.isin(parts, out[out > 0])
        cols = slice(int(xc - half), int(xc + half) + 1)
        while bottom - top > 20 and skin[bottom, cols].mean() > 0.5:
            bottom -= 1
        while bottom - top > 20 and skin[top, cols].mean() > 0.5:
            top += 1
    keep = ndimage.binary_erosion(can & ~skin, iterations=2)     # not the edges: background shows there
    azimuth = (np.arange(W) + 0.5) / W * 360 - 180              # the texture's columns
    phi = (azimuth - direction + 180) % 360 - 180               # from the photo's direction
    seen = np.abs(phi) < 72
    x = xc - half * np.sin(np.radians(phi))                     # right in the photo: smaller angles
    y = top + (np.arange(Ht) + 0.5) / Ht * (bottom - top)
    xx, yy = np.meshgrid(x, y)
    colour = np.stack([ndimage.map_coordinates(rgb[..., i].astype(float), [yy, xx], order=1, mode="nearest")
                       for i in range(3)], -1) / 255
    ok = ndimage.map_coordinates(keep.astype(float), [yy, xx], order=1, mode="constant") > 0.5
    weight = np.where(ok & seen[None, :], np.cos(np.radians(phi))[None, :] ** 3, 0.0)
    return colour, weight, 2 * half / (bottom - top)


def wrap_can(cutouts: list, hands: list | None = None, size=(2048, 1024)) -> tuple[bytes, float, float]:
    """A solid can from cut-out photos (RGBA uint8 arrays) taken a quarter turn apart, the same
    way round each time. Returns the GLB (height 1, standing on y = 0, axis at x = z = 0), its
    width / height, and the turn found between photos (degrees: +90 or -90)."""
    from PIL import Image
    from scipy import ndimage
    W, Ht = size
    hands = (list(hands or []) + [[]] * len(cutouts))[:len(cutouts)]
    best = None
    for turn in ((90.0, -90.0) if len(cutouts) > 1 else (90.0,)):
        views = [_unroll(c, hands[k], FACE_CAMERA + k * turn, W, Ht) for k, c in enumerate(cutouts)]
        # How well neighbours agree where both see the surface: the wrong way round, they do not.
        cost = 0.0
        for k in range(len(views)):
            (c1, w1, _), (c2, w2, _) = views[k], views[(k + 1) % len(views)]
            both = np.minimum(w1, w2)
            if len(views) > 2 or k == 0:
                cost += float((np.abs(c1 - c2).sum(-1) * both).sum() / max(both.sum(), 1e-6))
        if best is None or cost < best[0]:
            best = (cost, turn, views)
    _, turn, views = best
    colour = sum(c * w[..., None] for c, w, _ in views)
    weight = sum(w for _, w, _ in views)
    have = weight > 0.05
    image = np.where(have[..., None], colour / np.maximum(weight, 1e-9)[..., None], 0)
    seen_colours = image[have] if have.any() else np.zeros((1, 3))
    lum = seen_colours @ _LUM
    base = np.median(seen_colours[lum <= np.median(lum)], axis=0)
    if have.any() and not have.all():
        dist, (iy, ix) = ndimage.distance_transform_edt(~have, return_indices=True)
        t = np.clip(dist / 40.0, 0, 1)[..., None]
        image = np.where(have[..., None], image, image[iy, ix] * (1 - t) + base * t)
    elif not have.any():
        image[:] = base
    png = io.BytesIO()
    Image.fromarray((np.clip(image, 0, 1) * 255).round().astype(np.uint8)).save(png, "PNG", optimize=True)
    aspect = float(np.median([a for _, _, a in views]))

    # The can: its side wearing the photos, a lid and a bottom.
    N, rows, H = 128, 9, 1.0
    R = aspect * H / 2
    a = np.linspace(-np.pi, np.pi, N + 1)
    ring = np.stack([np.cos(a), np.zeros_like(a), np.sin(a)], 1)
    ys = np.linspace(0, H, rows)
    side_p = np.concatenate([ring * R + [0, y, 0] for y in ys])
    side_n = np.tile(ring, (rows, 1))
    side_uv = np.concatenate([np.stack([np.arange(N + 1) / N, np.full(N + 1, 1 - y / H)], 1) for y in ys])
    side_f = np.concatenate([_strip(i * (N + 1), (i + 1) * (N + 1), N) for i in range(rows - 1)])
    discs = []
    for y, up, name in ((H, 1.0, "lid"), (0.0, -1.0, "plain")):
        p = np.concatenate([ring * R + [0, y, 0], [[0, y, 0]]])
        n = np.tile([0, up, 0], (N + 2, 1))
        f = np.array([[N + 1, i, i + 1] for i in range(N)])
        discs.append((p, n, None, _wind(p, n, f), name))
    prims = [(side_p, side_n, side_uv, _wind(side_p, side_n, side_f), "print")] + discs
    lin = srgb_to_linear(base)
    return _glb(prims, png.getvalue(), {"lid": np.array([0.55, 0.56, 0.58]), "plain": lin}), aspect, turn


# ----------------------------------------------------------------------------- glTF

def _glb(primitives, png: bytes, colours: dict) -> bytes:
    blob, views, accessors = bytearray(), [], []

    def add(data: bytes, target: int | None = None) -> int:
        blob.extend(b"\0" * (-len(blob) % 4))
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), **({"target": target} if target else {})})
        blob.extend(data)
        return len(views) - 1

    def accessor(array: np.ndarray, kind: str, component: int, target: int, bounds=False) -> int:
        view = add(np.ascontiguousarray(array).tobytes(), target)
        acc = {"bufferView": view, "componentType": component, "count": len(array), "type": kind}
        if bounds:
            acc.update(min=array.min(0).tolist(), max=array.max(0).tolist())
        accessors.append(acc)
        return len(accessors) - 1

    materials = {
        "print": {"name": "print", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0},
                  "metallicFactor": 0.0, "roughnessFactor": 0.35}, "doubleSided": True},
    }
    for name, rgb in colours.items():
        materials[name] = {"name": name, "pbrMetallicRoughness": {
            "baseColorFactor": [*np.clip(rgb, 0, 1).round(5).tolist(), 1.0],
            "metallicFactor": 0.0, "roughnessFactor": 0.35}, "doubleSided": True}
    order = list(materials)
    prims = []
    for pos, nrm, uv, faces, material in primitives:
        attributes = {"POSITION": accessor(pos.astype("<f4"), "VEC3", 5126, 34962, bounds=True),
                      "NORMAL": accessor(nrm.astype("<f4"), "VEC3", 5126, 34962)}
        if uv is not None:
            attributes["TEXCOORD_0"] = accessor(uv.astype("<f4"), "VEC2", 5126, 34962)
        indices = accessor(faces.astype("<u4").reshape(-1), "SCALAR", 5125, 34963)
        prims.append({"attributes": attributes, "indices": indices, "material": order.index(material), "mode": 4})
    image_view = add(png)
    doc = {
        "asset": {"version": "2.0", "generator": "move_the_bot solid_mug.py"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": "solid"}],
        "meshes": [{"primitives": prims}],
        "materials": [materials[m] for m in order],
        "textures": [{"source": 0, "sampler": 0}],
        "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 33071}],
        "images": [{"bufferView": image_view, "mimeType": "image/png"}],
        "buffers": [{"byteLength": 0}], "bufferViews": views, "accessors": accessors,
    }
    blob.extend(b"\0" * (-len(blob) % 4))
    doc["buffers"][0]["byteLength"] = len(blob)
    text = json.dumps(doc, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    chunks = struct.pack("<II", len(text), 0x4E4F534A) + text + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob)
    return struct.pack("<III", 0x46546C67, 2, 12 + len(chunks)) + chunks


def read_points_glb(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    """The points and sRGB colours of a point-cloud GLB as photo_to_3d.py writes it."""
    length = struct.unpack("<I", data[12:16])[0]
    doc = json.loads(data[20:20 + length])
    blob = data[20 + length + 8:]
    prim = doc["meshes"][0]["primitives"][0]
    if prim.get("mode", 4) != 0:
        raise ValueError("not a point cloud (it is already a solid model?)")

    def read(index: int) -> np.ndarray:
        acc = doc["accessors"][index]
        view = doc["bufferViews"][acc["bufferView"]]
        width = {"VEC3": 3, "VEC4": 4}[acc["type"]]
        dtype = {5126: "<f4", 5121: "u1", 5123: "<u2"}[acc["componentType"]]
        a = np.frombuffer(blob, dtype, acc["count"] * width, view.get("byteOffset", 0) + acc.get("byteOffset", 0))
        a = a.reshape(-1, width).astype(np.float64)
        return a / {"<f4": 1, "u1": 255, "<u2": 65535}[dtype]

    points = read(prim["attributes"]["POSITION"])
    colour = read(prim["attributes"]["COLOR_0"])[:, :3] if "COLOR_0" in prim["attributes"] else np.full((len(points), 3), 0.5)
    return points, linear_to_srgb(colour)          # glTF vertex colours are linear


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("glb", type=Path, help="a point cloud made by photo_to_3d.py or the scanner")
    ap.add_argument("-o", "--out", type=Path, help="where to write it (default: replace the input, keeping a backup)")
    ap.add_argument("--force", action="store_true", help="even if the points do not look like a cylinder")
    args = ap.parse_args()
    points, srgb = read_points_glb(args.glb.read_bytes())
    if not args.force and not fits_cylinder(points):
        sys.exit("These points do not look like a mug, cup or can standing up (--force to try anyway).")
    data = solid_glb(points, srgb)
    out = args.out or args.glb
    if out == args.glb:
        backup = args.glb.parent / "backup" / f"{args.glb.stem}-points.glb"
        backup.parent.mkdir(exist_ok=True)
        shutil.copy2(args.glb, backup)
        print(f"Kept the points in {backup}")
    out.write_bytes(data)
    print(f"Wrote {out}: a solid model, {len(data) / 1e6:.1f} MB. Rebuild with ./run.sh --rebuild to see it.")


if __name__ == "__main__":
    main()
