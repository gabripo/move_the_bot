"""Object scanner (optional): show an object to the webcam, and it becomes an object on the table.

Start it with `./run.sh --scan` (Docker Compose profile "scan"). The browser sends a photo, a
name and the object's height. Idol, Speridlabs' open image-to-3D model, turns the photo into a
3D Gaussian splat; the splat becomes a point-cloud model in the shared model cache, with the
object's real size next to it. From then on "create a <name>" puts it on the table, and the
robot plans and grasps it like any other object.

Where Idol runs (IDOL_BACKEND):
  demo    Idol's public demo on Hugging Face (default). No GPU needed; a short free daily quota,
          or a larger one with HF_TOKEN set.
  local   the Idol SDK on this machine's GPU (about 8 GB of video memory; see
          docs/your-own-objects.md).
  remote  another scan server at IDOL_URL, for example on a GPU PC in the network running this
          same server with IDOL_BACKEND=local (the way OLLAMA_URL points at Ollama).
  file    always the splat at IDOL_FILE: for tests, and demos without a GPU or the internet.

Endpoints:
  GET  /health                          which backend, and where it runs
  POST /scan   image, name, height_cm   the model in the cache -> {name, model, size, ...}
  POST /splat  image                    only the splat (.ply): what a remote server answers
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path

import requests
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

import models3d                                   # the same files as the robot's (see Dockerfile.scan)
import photo_to_3d
from world import COLORS, canonical_kind

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("scan")

BACKEND = os.environ.get("IDOL_BACKEND", "demo").strip().lower()
MODELS_DIR = os.environ.get("MODELS_DIR", "/models")
GAUSSIANS = int(os.environ.get("IDOL_GAUSSIANS", "262144"))
WHERE = {
    "demo": "Idol's public demo on Hugging Face",
    "local": "Idol on this machine's GPU",
    "remote": f"a scan server at {os.environ.get('IDOL_URL', '?')}",
    "file": f"a fixed splat ({os.environ.get('IDOL_FILE', '?')})",
}
if BACKEND not in WHERE:
    raise SystemExit(f"IDOL_BACKEND must be one of {', '.join(WHERE)}, not {BACKEND!r}")

app = FastAPI(title="move_the_bot object scanner")
_busy = threading.Lock()                          # one scan at a time: one GPU
_pipeline = None


def object_name(text: str) -> str:
    """'a red Stapler!' -> 'stapler': the name the robot will use for it."""
    words = re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split()
    while words and words[0] in ("a", "an", "the", "my", "this", "that", "your"):
        words.pop(0)
    if len(words) > 1 and words[0] in COLORS:     # "red cube" means a plain red shape
        words.pop(0)
    name = " ".join(words)[:30].strip()
    if not name:
        raise HTTPException(400, "Give the object a name, such as 'stapler'.")
    return canonical_kind(name)


def make_splat(photo: Path, splat: Path) -> None:
    """Run Idol on the photo, wherever IDOL_BACKEND says, and write the splat."""
    global _pipeline
    if BACKEND == "file":
        shutil.copy(os.environ["IDOL_FILE"], splat)
    elif BACKEND == "remote":
        with open(photo, "rb") as f:
            r = requests.post(os.environ["IDOL_URL"].rstrip("/") + "/splat",
                              files={"image": (photo.name, f, "image/jpeg")}, timeout=900)
        if r.status_code != 200:
            raise HTTPException(502, f"The scan server at IDOL_URL answered {r.status_code}: {r.text[:200]}")
        splat.write_bytes(r.content)
    elif BACKEND == "local":
        from idol import IdolPipeline             # installed only where there is a GPU
        if _pipeline is None:
            log.info("Loading Idol (the first time downloads the weights)…")
            _pipeline = IdolPipeline.from_pretrained(os.environ.get("IDOL_WEIGHTS", "speridlabs/idol"))
        _pipeline(str(photo), mode="real", seed=42, num_gaussians=GAUSSIANS).gaussian.save_ply(str(splat))
    else:
        from gradio_client import Client, handle_file
        try:
            client = Client("speridlabs/idol", token=os.environ.get("HF_TOKEN") or None, verbose=False)
            result, _, _ = client.predict(handle_file(str(photo)), "Real photo", 50, 3.0, 3.0, 42, False,
                                          f"{GAUSSIANS:,}", api_name="/run")
        except Exception as e:                    # noqa: BLE001  the demo's errors are plain exceptions
            text = str(e)
            if "quota" in text.lower():
                raise HTTPException(503, "Idol's free demo quota is used up for now. Set HF_TOKEN for a "
                                         "larger one, or run Idol on a GPU (IDOL_BACKEND=local or remote).")
            raise HTTPException(502, f"Idol's demo failed: {text[:200]}")
        shutil.copy(result, splat)


def _photo(image: UploadFile, folder: Path) -> Path:
    data = image.file.read()
    if not data:
        raise HTTPException(400, "No photo.")
    if len(data) > 15_000_000:
        raise HTTPException(413, "The photo is too large (15 MB at most).")
    path = folder / "photo.jpg"
    path.write_bytes(data)
    return path


@app.get("/health")
def health() -> dict:
    return {"ok": True, "backend": BACKEND, "where": WHERE[BACKEND], "gaussians": GAUSSIANS}


@app.post("/scan")
def scan(image: UploadFile = File(...), name: str = Form(...), height_cm: float = Form(10.0)) -> dict:
    kind = object_name(name)
    if not 2 <= height_cm <= 30:
        raise HTTPException(400, "The height must be between 2 and 30 cm: the arm lifts small things.")
    if not _busy.acquire(blocking=False):
        raise HTTPException(409, "Another scan is running; try again in a moment.")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            start = time.monotonic()
            splat = Path(tmp) / "splat.ply"
            make_splat(_photo(image, Path(tmp)), splat)
            points, colours = photo_to_3d.splat_to_points(photo_to_3d.read_ply(splat))
            width, depth, height = photo_to_3d.real_size(points, height_cm / 100)
            size = (min(width, 0.25), min(depth, 0.25), height)
            model = models3d.save_scanned(kind, photo_to_3d.glb_bytes(points, colours), size, MODELS_DIR)
            took = time.monotonic() - start
    finally:
        _busy.release()
    log.info("Scanned %s in %.1f s: %d points, %s", kind, took, len(points), size)
    return {"name": kind, "model": model, "size": [round(v, 3) for v in size], "points": len(points),
            "seconds": round(took, 1), "backend": BACKEND, "where": WHERE[BACKEND]}


@app.post("/splat")
def splat_only(image: UploadFile = File(...)) -> Response:
    if not _busy.acquire(blocking=False):
        raise HTTPException(409, "Another scan is running; try again in a moment.")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            splat = Path(tmp) / "splat.ply"
            make_splat(_photo(image, Path(tmp)), splat)
            return Response(splat.read_bytes(), media_type="application/octet-stream")
    finally:
        _busy.release()
