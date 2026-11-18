"""Object scanner (optional): show an object to the webcam, and it becomes an object on the table.

Start it with `./run.sh --scan` (Docker Compose profile "scan"). The browser sends one photo, or
several of the object turned between them (up to 8), a name and the object's height. Idol,
Speridlabs' open image-to-3D model, turns each photo into a 3D Gaussian splat; with several, the
splats are fused into one (photo_to_3d.fuse_splats), so the back is seen rather than invented.
The splat becomes a point-cloud model in the shared model cache, with the object's real size next
to it. From then on "create a <name>" puts it on the table, and the robot plans and grasps it like
any other object.

Where Idol runs (IDOL_BACKEND):
  demo    Idol's public demo on Hugging Face (default). No GPU needed; a short free daily quota,
          or a larger one with HF_TOKEN set. Uses the first photo only, to spare the quota.
  local   the Idol SDK on this machine's GPU (about 8 GB of video memory). On a GPU PC that also
          serves Ollama, docker/idol-server/idol-server.sh sets this up; FREE_OLLAMA_URL then
          unloads Ollama's model before each scan, and IDOL_KEEP_LOADED=0 (the default) frees
          the video memory again after it.
  remote  another scan server at IDOL_URL, for example on a GPU PC in the network running this
          same server with IDOL_BACKEND=local (the way OLLAMA_URL points at Ollama).
  file    always the splat at IDOL_FILE: for tests, and demos without a GPU or the internet.

Endpoints (image: one or more photos; gaussians, optional: the detail per photo, 32,768 to
1,048,576; default IDOL_GAUSSIANS):
  GET  /health                                     which backend, where it runs, which GPU
  GET  /progress                                   the scan running now: step, photo k of n, seconds
  POST /scan   image, name, height_cm, gaussians   the model in the cache -> {name, model, size, ...}
  POST /splat  image, gaussians                    only the (fused) splat, .ply: what a remote server answers
  GET  /scans                                      the objects scanned so far -> [{name, model, size, made}]
  DELETE /scans/{name}                             forget one: 'create a <name>' draws it as before the scan
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
IDOL_URL = os.environ.get("IDOL_URL", "").rstrip("/")
MAX_VIEWS = 8
WHERE = {
    "demo": "Idol's public demo on Hugging Face",
    "local": "Idol on this machine's GPU",
    "remote": f"a scan server at {IDOL_URL or '?'}",
    "file": f"a fixed splat ({os.environ.get('IDOL_FILE', '?')})",
}
if BACKEND not in WHERE:
    raise SystemExit(f"IDOL_BACKEND must be one of {', '.join(WHERE)}, not {BACKEND!r}")

app = FastAPI(title="move_the_bot object scanner")
_busy = threading.Lock()                          # one scan at a time: one GPU
_pipeline = None
KEEP_LOADED = os.environ.get("IDOL_KEEP_LOADED", "0") == "1"
FREE_OLLAMA_URL = os.environ.get("FREE_OLLAMA_URL", "").rstrip("/")

# What the scan running now is doing, for GET /progress. Replaced whole, never changed in place,
# so a reader always sees one consistent state.
PROGRESS: dict = {"state": "idle"}


def _progress(**changes) -> None:
    global PROGRESS
    PROGRESS = {**PROGRESS, **changes}


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


def _gpu_name() -> str | None:
    try:
        import torch
        return torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    except ImportError:
        return None


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


def _idol_demo(photo: Path, gaussians: int) -> Path:
    from gradio_client import Client, handle_file
    try:
        client = Client("speridlabs/idol", token=os.environ.get("HF_TOKEN") or None, verbose=False)
        choice = min(DEMO_CHOICES, key=lambda c: abs(c - gaussians))      # the nearest it offers
        result, _, _ = client.predict(handle_file(str(photo)), "Real photo", 50, 3.0, 3.0, 42, False,
                                      f"{choice:,}", api_name="/run")
    except Exception as e:                        # noqa: BLE001  the demo's errors are plain exceptions
        text = str(e)
        if "quota" in text.lower():
            raise HTTPException(503, "Idol's free demo quota is used up for now. Set HF_TOKEN for a "
                                     "larger one, or run Idol on a GPU (IDOL_BACKEND=local or remote).")
        raise HTTPException(502, f"Idol's demo failed: {text[:200]}")
    return Path(result)


def make_splat(photos: list[Path], gaussians: int) -> tuple[bytes, list[float]]:
    """Run Idol on the photos, wherever IDOL_BACKEND says: one splat (.ply bytes), fused when
    there are several photos, and the angle each photo was found at (degrees, the first at 0)."""
    global _pipeline
    if BACKEND == "file":
        return Path(os.environ["IDOL_FILE"]).read_bytes(), [0.0]
    if BACKEND == "remote":
        _progress(step="sending")
        files = [("image", (p.name, p.read_bytes(), "image/jpeg")) for p in photos]
        try:
            r = requests.post(IDOL_URL + "/splat", data={"gaussians": gaussians}, files=files, timeout=3600)
        except requests.RequestException:
            raise HTTPException(503, "The GPU PC's scan server does not answer: is it on, and its AI "
                                     "switched on (ai-switch on)?")
        if r.status_code != 200:
            raise HTTPException(502, f"The scan server at IDOL_URL answered {r.status_code}: {r.text[:200]}")
        angles = [float(a) for a in r.headers.get("X-View-Angles", "0").split(",")]
        return r.content, angles
    if BACKEND == "demo":
        if len(photos) > 1:
            log.info("Idol's public demo: using the first of %d photos (its quota is small)", len(photos))
        _progress(step="idol", view=1, views=1)
        return _idol_demo(photos[0], gaussians).read_bytes(), [0.0]

    _free_ollama()
    splats = []
    try:
        if _pipeline is None:
            _progress(step="loading")
            _pipeline = _local_pipeline()
        for k, photo in enumerate(photos):                # the model stays loaded for all of them
            _progress(step="idol", view=k + 1, views=len(photos), view_started=time.time())
            out = photo.with_suffix(".ply")
            _pipeline(str(photo), mode="real", seed=42, num_gaussians=gaussians).gaussian.save_ply(str(out))
            splats.append(out.read_bytes())
    finally:
        _release_pipeline()
    if len(splats) == 1:
        return splats[0], [0.0]
    _progress(step="fusing")
    fused, angles = photo_to_3d.fuse_splats([photo_to_3d.parse_ply(s) for s in splats], step=360 / len(splats))
    log.info("Fused %d views, found at %s degrees", len(splats), [round(a) for a in angles])
    return photo_to_3d.ply_bytes(fused), angles


def _photos(images: list[UploadFile], folder: Path) -> list[Path]:
    if not images:
        raise HTTPException(400, "No photo.")
    if len(images) > MAX_VIEWS:
        raise HTTPException(400, f"{MAX_VIEWS} photos at most.")
    paths = []
    for k, image in enumerate(images):
        data = image.file.read()
        if not data:
            raise HTTPException(400, "An empty photo.")
        if len(data) > 15_000_000:
            raise HTTPException(413, "A photo is too large (15 MB at most).")
        paths.append(folder / f"photo_{k}.jpg")
        paths[-1].write_bytes(data)
    return paths


def _run(kind: str | None, images: list[UploadFile], work):
    """One scan at a time, its progress kept for GET /progress."""
    if not _busy.acquire(blocking=False):
        raise HTTPException(409, "Another scan is running; try again in a moment.")
    try:
        _progress_reset(kind, len(images))
        with tempfile.TemporaryDirectory() as tmp:
            result = work(_photos(images, Path(tmp)))
        _progress(state="done", step="done", seconds=round(time.time() - PROGRESS["started"], 1))
        return result
    except Exception as e:
        _progress(state="failed", step="failed", message=str(getattr(e, "detail", e))[:200])
        raise
    finally:
        _busy.release()


def _progress_reset(kind: str | None, views: int) -> None:
    global PROGRESS
    PROGRESS = {"state": "running", "step": "starting", "name": kind, "view": 0, "views": views,
                "started": time.time(), "backend": BACKEND}


@app.get("/health")
def health() -> dict:
    answer = {"ok": True, "backend": BACKEND, "where": WHERE[BACKEND], "gaussians": GAUSSIANS,
              "max_views": MAX_VIEWS}
    if BACKEND == "remote":                       # no Scan button while the GPU PC's AI is off
        try:
            r = requests.get(IDOL_URL + "/health", timeout=3)
            r.raise_for_status()
            answer["gpu"] = r.json().get("gpu")
        except (requests.RequestException, ValueError):
            answer.update(ok=False, reason="the GPU PC's scan server does not answer")
    if BACKEND == "local":
        answer["gpu"] = _gpu_name()
        try:
            import torch
            answer["rocm"] = torch.version.hip
        except ImportError:
            pass
    return answer


@app.get("/progress")
def progress() -> dict:
    """The scan running now (or the last one): step (starting, sending, loading, idol, fusing,
    model, done, failed), photo `view` of `views`, and seconds so far. With a remote backend the
    GPU PC's own progress fills in the steps it runs."""
    p = dict(PROGRESS)
    if p.get("state") == "running" and BACKEND == "remote" and p.get("step") == "sending":
        try:
            remote = requests.get(IDOL_URL + "/progress", timeout=2).json()
            if remote.get("state") == "running":
                p.update({k: remote[k] for k in ("step", "view", "views", "view_started") if k in remote})
        except (requests.RequestException, ValueError):
            pass
    if p.get("state") == "running":
        p["seconds"] = round(time.time() - p["started"], 1)
        if "view_started" in p:
            p["view_seconds"] = round(time.time() - p.pop("view_started"), 1)
    return p


@app.post("/scan")
def scan(image: list[UploadFile] = File(...), name: str = Form(...), height_cm: float = Form(10.0),
         gaussians: int | None = Form(None)) -> dict:
    kind = object_name(name)
    n = detail(gaussians)
    if not 2 <= height_cm <= 30:
        raise HTTPException(400, "The height must be between 2 and 30 cm: the arm lifts small things.")

    def work(photos: list[Path]) -> dict:
        start = time.monotonic()
        splat, angles = make_splat(photos, n)
        _progress(step="model")
        points, colours = photo_to_3d.splat_to_points(photo_to_3d.parse_ply(splat))
        width, depth, height = photo_to_3d.real_size(points, height_cm / 100)
        size = (min(width, 0.25), min(depth, 0.25), height)
        model = models3d.save_scanned(kind, photo_to_3d.glb_bytes(points, colours), size, MODELS_DIR)
        took = time.monotonic() - start
        log.info("Scanned %s from %d photo(s) in %.1f s: %d points, %s", kind, len(photos), took, len(points), size)
        return {"name": kind, "model": model, "size": [round(v, 3) for v in size], "points": len(points),
                "views": len(angles), "angles": [round(a) for a in angles], "seconds": round(took, 1),
                "backend": BACKEND, "where": WHERE[BACKEND]}

    return _run(kind, image, work)


@app.get("/scans")
def scans() -> list:
    found = []
    for kind in models3d.scanned_kinds(MODELS_DIR):
        glb = models3d.cache_file(kind, MODELS_DIR)
        found.append({"name": kind, "model": f"/models/cache/{glb.name}",
                      "size": models3d.scanned_size(kind, MODELS_DIR), "made": round(glb.stat().st_mtime)})
    return sorted(found, key=lambda s: -s["made"])


@app.delete("/scans/{name}")
def forget(name: str) -> dict:
    kind = object_name(name)
    if not models3d.forget_scanned(kind, MODELS_DIR):
        raise HTTPException(404, f"There is no scan of '{kind}'.")
    log.info("Forgot the scan of %s", kind)
    return {"removed": kind}


@app.post("/splat")
def splat_only(image: list[UploadFile] = File(...), gaussians: int | None = Form(None)) -> Response:
    n = detail(gaussians)

    def work(photos: list[Path]) -> Response:
        splat, angles = make_splat(photos, n)
        return Response(splat, media_type="application/octet-stream",
                        headers={"X-View-Angles": ",".join(f"{a:.1f}" for a in angles)})

    return _run(None, image, work)
