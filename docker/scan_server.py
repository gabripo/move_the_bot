"""Object scanner (optional): show an object to the webcam, and it becomes an object on the table.

Start it with `./run.sh --scan` (Docker Compose profile "scan"). The browser sends a photo, a
name and the object's height. Idol, Speridlabs' open image-to-3D model, turns the photo into a
3D Gaussian splat; the splat becomes a point-cloud model in the shared model cache, with the
object's real size next to it. From then on "create a <name>" puts it on the table, and the
robot plans and grasps it like any other object.

Where Idol runs (IDOL_BACKEND):
  demo    Idol's public demo on Hugging Face (default). No GPU needed; a short free daily quota,
          or a larger one with HF_TOKEN set.
  local   the Idol SDK on this machine's GPU (about 8 GB of video memory). On a GPU PC that also
          serves Ollama, docker/idol-server/idol-server.sh sets this up; FREE_OLLAMA_URL then
          unloads Ollama's model before each scan, and IDOL_KEEP_LOADED=0 (the default) frees
          the video memory again after it.
  remote  another scan server at IDOL_URL, for example on a GPU PC in the network running this
          same server with IDOL_BACKEND=local (the way OLLAMA_URL points at Ollama).
  file    always the splat at IDOL_FILE: for tests, and demos without a GPU or the internet.

Endpoints (gaussians, optional: the detail, 32,768 to 1,048,576; default IDOL_GAUSSIANS):
  GET  /health                                     which backend, and where it runs
  POST /scan   image, name, height_cm, gaussians   the model in the cache -> {name, model, size, ...}
  POST /splat  image, gaussians                    only the splat (.ply): what a remote server answers
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
KEEP_LOADED = os.environ.get("IDOL_KEEP_LOADED", "0") == "1"
FREE_OLLAMA_URL = os.environ.get("FREE_OLLAMA_URL", "").rstrip("/")


def _free_ollama() -> None:
    """Ask Ollama on this GPU to unload its models: a 14B model and Idol do not fit together in
    16 GB. The next language request loads the model again (a few seconds)."""
    if not FREE_OLLAMA_URL:
        return
    try:
        loaded = requests.get(f"{FREE_OLLAMA_URL}/api/ps", timeout=5).json().get("models", [])
        for model in loaded:
            requests.post(f"{FREE_OLLAMA_URL}/api/generate", json={"model": model["name"], "keep_alive": 0}, timeout=30)
            log.info("Unloaded %s from Ollama to make room for Idol", model["name"])
    except (requests.RequestException, ValueError) as e:
        log.warning("Could not ask Ollama to unload its model: %s", e)


def _local_pipeline():
    """Idol on this machine's GPU. Its fast path (torch.compile, cuDNN attention) is for NVIDIA;
    on AMD GPUs (ROCm) it is off unless IDOL_OPTIMIZE=1."""
    import torch
    from idol import IdolPipeline                 # installed only where there is a GPU
    wanted = os.environ.get("IDOL_OPTIMIZE", "auto")
    optimize = (wanted == "1") or (wanted == "auto" and torch.version.hip is None)
    log.info("Loading Idol on %s (optimize=%s; the first time downloads the weights)…",
             torch.cuda.get_device_name(0) if torch.cuda.is_available() else "the CPU", optimize)
    return IdolPipeline.from_pretrained(os.environ.get("IDOL_WEIGHTS", "speridlabs/idol"), optimize=optimize)


def _release_pipeline() -> None:
    global _pipeline
    if KEEP_LOADED or _pipeline is None:
        return
    import gc
    import torch
    _pipeline = None
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()                  # the video memory goes back to games and Ollama


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


DEMO_CHOICES = (65536, 131072, 262144, 524288, 1048576)      # what Idol's public demo offers


def detail(gaussians: int | None) -> int:
    """How many Gaussians: 32,768 to 1,048,576, a multiple of 32 (Idol's limits)."""
    n = GAUSSIANS if gaussians is None else int(gaussians)
    if not 32768 <= n <= 1048576:
        raise HTTPException(400, "gaussians must be between 32,768 and 1,048,576.")
    return n - n % 32


def make_splat(photo: Path, splat: Path, gaussians: int) -> None:
    """Run Idol on the photo, wherever IDOL_BACKEND says, and write the splat."""
    global _pipeline
    if BACKEND == "file":
        shutil.copy(os.environ["IDOL_FILE"], splat)
    elif BACKEND == "remote":
        with open(photo, "rb") as f:
            r = requests.post(os.environ["IDOL_URL"].rstrip("/") + "/splat", data={"gaussians": gaussians},
                              files={"image": (photo.name, f, "image/jpeg")}, timeout=1800)
        if r.status_code != 200:
            raise HTTPException(502, f"The scan server at IDOL_URL answered {r.status_code}: {r.text[:200]}")
        splat.write_bytes(r.content)
    elif BACKEND == "local":
        _free_ollama()
        try:
            if _pipeline is None:
                _pipeline = _local_pipeline()
            _pipeline(str(photo), mode="real", seed=42, num_gaussians=gaussians).gaussian.save_ply(str(splat))
        finally:
            _release_pipeline()
    else:
        from gradio_client import Client, handle_file
        try:
            client = Client("speridlabs/idol", token=os.environ.get("HF_TOKEN") or None, verbose=False)
            choice = min(DEMO_CHOICES, key=lambda c: abs(c - gaussians))      # the nearest it offers
            result, _, _ = client.predict(handle_file(str(photo)), "Real photo", 50, 3.0, 3.0, 42, False,
                                          f"{choice:,}", api_name="/run")
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
    answer = {"ok": True, "backend": BACKEND, "where": WHERE[BACKEND], "gaussians": GAUSSIANS}
    if BACKEND == "local":
        try:
            import torch
            answer["gpu"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
            answer["rocm"] = torch.version.hip
        except ImportError:
            answer["gpu"] = None
    return answer


@app.post("/scan")
def scan(image: UploadFile = File(...), name: str = Form(...), height_cm: float = Form(10.0),
         gaussians: int | None = Form(None)) -> dict:
    kind = object_name(name)
    n = detail(gaussians)
    if not 2 <= height_cm <= 30:
        raise HTTPException(400, "The height must be between 2 and 30 cm: the arm lifts small things.")
    if not _busy.acquire(blocking=False):
        raise HTTPException(409, "Another scan is running; try again in a moment.")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            start = time.monotonic()
            splat = Path(tmp) / "splat.ply"
            make_splat(_photo(image, Path(tmp)), splat, n)
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
def splat_only(image: UploadFile = File(...), gaussians: int | None = Form(None)) -> Response:
    n = detail(gaussians)
    if not _busy.acquire(blocking=False):
        raise HTTPException(409, "Another scan is running; try again in a moment.")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            splat = Path(tmp) / "splat.ply"
            make_splat(_photo(image, Path(tmp)), splat, n)
            return Response(splat.read_bytes(), media_type="application/octet-stream")
    finally:
        _busy.release()
