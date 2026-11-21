#!/usr/bin/env python3
"""Write a small synthetic Gaussian splat (a striped cylinder), for testing the object scanner
without Idol: start the scanner with IDOL_BACKEND=file and IDOL_FILE pointing at it.

    python3 tests/e2e/make_test_splat.py test-splat.ply

Pure Python on purpose, so CI needs nothing installed. The layout is the one Idol writes.
"""
import math
import random
import struct
import sys

FIELDS = ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
          "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]


def main(path: str, n: int = 20000) -> None:
    rng = random.Random(7)
    rows = []
    for _ in range(n):
        angle, height = rng.uniform(0, 2 * math.pi), rng.uniform(0, 0.8)
        stripe = int(height * 10) % 2                     # blue and orange bands
        dc = (1.5, 0.2, -1.7) if stripe else (-1.7, -0.5, 1.5)
        x, y, z = 0.3 * math.cos(angle), 0.4 - height, 0.3 * math.sin(angle)   # y down, as Idol
        rows.append(struct.pack("<17f", x, y, z, 0, 0, 0, *dc, 5.0, -5.0, -5.0, -5.0, 1, 0, 0, 0))
    header = f"ply\nformat binary_little_endian 1.0\nelement vertex {n}\n"
    header += "".join(f"property float {f}\n" for f in FIELDS) + "end_header\n"
    with open(path, "wb") as f:
        f.write(header.encode() + b"".join(rows))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "test-splat.ply")
