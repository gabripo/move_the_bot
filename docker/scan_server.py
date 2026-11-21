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
  GET  /progress                                   the scan running now: step, photo k of n, seconds,
                                                   and small pictures of what Idol was shown (cutouts)
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

try:
    import solid_mug                              # scripts/solid_mug.py (numpy, scipy, Pillow)
except ImportError:                               # an older image (the GPU PC's Idol server): points only
    solid_mug = None

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


# ------------------------------------------------------------------ the object, cut out
#
# Idol removes the background itself (BiRefNet), but BiRefNet keeps whatever stands out, and a
# face right behind the object stands out too: it became part of the model. So the object is cut
# out first: SAM 2 is told the object is in the middle of the photo (the scanner's square), and
# only what BiRefNet and SAM 2 both call the object stays. Idol then gets a photo with a
# transparent background and uses it as it is. CUTOUT=0 leaves it to Idol alone.
CUTOUT = os.environ.get("CUTOUT", "1") != "0"
CUTOUT_MODEL = os.environ.get("CUTOUT_MODEL", "facebook/sam2.1-hiera-small")
_cutter = None
_cutter_broken = ""                               # why SAM 2 could not be loaded: then no more tries


class Cutter:
    def __init__(self, device, background_remover=None):
        from transformers import Sam2Model, Sam2Processor
        self.processor = Sam2Processor.from_pretrained(CUTOUT_MODEL)
        self.model = Sam2Model.from_pretrained(CUTOUT_MODEL).to(device).eval()
        self.device = device
        self.remover = background_remover           # Idol's BiRefNet, when there is one

    def __call__(self, image):
        """The object in the middle of `image`, on a transparent background (RGBA, the size of
        `image`), and how it was found."""
        import numpy as np
        import torch
        from PIL import Image, ImageFilter
        rgb = image.convert("RGB")
        w, h = rgb.size
        def ask(points, box=None):
            """SAM 2's objects for these prompts: (score, area, mask), the plausible ones."""
            kwargs = {"input_boxes": [[box]]} if box else {}
            inputs = self.processor(images=rgb, input_points=[[points]], input_labels=[[[1] * len(points)]],
                                    return_tensors="pt", **kwargs).to(self.device)
            with torch.no_grad():
                out = self.model(**inputs, multimask_output=True)
            masks = self.processor.post_process_masks(out.pred_masks.cpu(), inputs["original_sizes"])[0][0].numpy() > 0
            found = []
            for mask, score in zip(masks, out.iou_scores[0, 0].float().cpu().numpy()):
                mask = _around_center(mask)
                area = mask.mean()
                borders = sum(bool(edge.mean() > 0.25) for edge in (mask[0], mask[-1], mask[:, 0], mask[:, -1]))
                if 0.005 < area < 0.75 and borders <= 1:  # else the background, or a speck
                    found.append((float(score), float(area), mask))
            return found

        def pick(found):
            """The whole object: the largest answer SAM 2 is still fairly sure of."""
            sure = [f for f in found if f[0] >= max(0.5, max((f[0] for f in found), default=0) - 0.2)]
            return max(sure, key=lambda f: f[1]) if sure else None

        # The object is held in the middle of the square: SAM 2 is asked with a point there (and
        # with two more close to it). Each answer comes in three sizes (a detail, a part, the whole).
        centre = [w / 2, h / 2]
        best = pick(ask([centre]) + ask([centre, [w / 2, h * 0.46], [w / 2, h * 0.54]]))
        self.found = [best and (round(best[0], 2), round(best[1], 3))]
        # Often that is a detail of the object (a print on a mug). Asked again with a box twice its
        # size, SAM 2 answers with the main thing in the box: the object. Until it stops growing.
        for _ in range(3):
            if best is None:
                break
            ys, xs = np.nonzero(best[2])
            cx, cy, half = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2, max(np.ptp(xs), np.ptp(ys))
            box = [max(0, cx - half), max(0, cy - half), min(w - 1, cx + half), min(h - 1, cy + half)]
            bigger = pick([f for f in ask([centre], box) if f[1] > best[1] * 1.15 and f[0] >= 0.6
                           and (f[2] & best[2]).sum() >= 0.8 * best[2].sum()])
            if bigger is None:
                break
            best = bigger
            self.found.append((round(best[0], 2), round(best[1], 3)))
        if best is None:
            return None, "SAM 2 found no object in the middle"
        best_score, _, best = best
        # Thin strands hanging off it (straps, cables, hair) go: an opening, then the middle part only.
        size = max(3, (min(w, h) // 110) | 1)
        opened = np.array(Image.fromarray(best.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(size))
                          .filter(ImageFilter.MaxFilter(size))) > 0
        if opened.sum() > 0.85 * best.sum():
            best = _around_center(opened)
        alpha = best
        how = f"SAM 2 ({best_score:.2f})"
        if self.remover is not None:
            # What BiRefNet calls foreground, within (a little more than) SAM's object: its edges are finer.
            fine = np.array(self.remover.remove_background(rgb).getchannel(3)) > 127
            grown = np.array(Image.fromarray(best.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(15))) > 0
            both = fine & grown
            if both.sum() > 0.6 * best.sum():
                alpha, how = both, how + " ∩ BiRefNet"
        out_image = rgb.copy()
        out_image.putalpha(Image.fromarray(alpha.astype(np.uint8) * 255))
        return out_image, how


def _around_center(mask):
    """Only the part of `mask` connected to the middle of the picture (specks elsewhere dropped)."""
    import numpy as np
    h, w = mask.shape
    if not mask[h // 2, w // 2]:
        return np.zeros_like(mask)
    step = max(1, max(h, w) // 256)                  # grow the region on a small copy: fast enough
    small = mask[::step, ::step]
    region = np.zeros_like(small)
    region[small.shape[0] // 2, small.shape[1] // 2] = True
    while True:
        grown = region.copy()
        grown[1:] |= region[:-1]; grown[:-1] |= region[1:]; grown[:, 1:] |= region[:, :-1]; grown[:, :-1] |= region[:, 1:]
        grown &= small
        if (grown == region).all():
            break
        region = grown
    keep = np.repeat(np.repeat(region, step, 0), step, 1)[:h, :w]
    big = np.zeros_like(mask)
    big[:keep.shape[0], :keep.shape[1]] = keep
    return mask & big


def _load_cutter() -> None:
    global _cutter, _cutter_broken
    if CUTOUT and _cutter is None and not _cutter_broken:
        log.info("Loading %s to cut out the objects…", CUTOUT_MODEL)
        try:
            _cutter = Cutter(_pipeline.device, getattr(_pipeline, "background_remover", None))
        except Exception as e:
            _cutter_broken = str(e)[:200]
            raise


def _cutout(photo: Path) -> Path:
    """The photo with only the object left (a PNG next to it), or the photo itself when that fails."""
    if not CUTOUT or _cutter_broken:
        return photo
    try:
        from PIL import Image
        _load_cutter()
        image = Image.open(photo)
        image.thumbnail((1024, 1024))
        cut, how = _cutter(image)
        if cut is None:
            log.info("%s: %s; Idol removes the background itself", photo.name, how)
            return photo
        out = photo.with_name(photo.stem + "_cut.png")
        cut.save(out)
        log.info("%s: cut out with %s", photo.name, how)
        return out
    except Exception as e:                        # no SAM 2 here, no internet the first time…
        log.warning("Could not cut out %s (%s); Idol removes the background itself", photo.name, e)
        return photo


def _preview(photo: Path) -> str:
    """A small JPEG (data URL) of what Idol sees: the object cut out, cropped, on black."""
    import base64
    import io
    from PIL import Image
    try:
        image = _pipeline.preprocess(str(photo), mode="real") if hasattr(_pipeline, "preprocess") else Image.open(photo)
        image = image.convert("RGB")
        image.thumbnail((160, 160))
        buf = io.BytesIO()
        image.save(buf, "JPEG", quality=80)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


def _release_pipeline() -> None:
    global _pipeline, _cutter
    if KEEP_LOADED or _pipeline is None:
        return
    import gc
    import torch
    _pipeline = None
    _cutter = None
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
        if CUTOUT and _cutter is None:
            _progress(step="loading")
            try:
                _load_cutter()
            except Exception as e:                    # then Idol removes the backgrounds itself
                log.warning("No cut-outs: %s", e)
        seen = []                                         # what Idol was shown, for the progress
        for k, photo in enumerate(photos):                # the model stays loaded for all of them
            _progress(step="idol", view=k + 1, views=len(photos), view_started=time.time(), cutouts=seen)
            cut = _cutout(photo)
            seen = seen + [_preview(cut)]
            _progress(cutouts=seen)
            out = photo.with_suffix(".ply")
            _pipeline(str(cut), mode="real", seed=42, num_gaussians=gaussians).gaussian.save_ply(str(out))
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
                if remote.get("cutouts"):
                    _progress(cutouts=remote["cutouts"])  # kept for the rest of the scan
                    p["cutouts"] = remote["cutouts"]
        except (requests.RequestException, ValueError):
            pass
    if p.get("state") == "running":
        p["seconds"] = round(time.time() - p["started"], 1)
        if "view_started" in p:
            p["view_seconds"] = round(time.time() - p.pop("view_started"), 1)
    return p


def _solid(kind: str, points, colours) -> tuple[bytes | None, bool]:
    """A mug, cup or can (by its name) whose points look like a cylinder becomes a solid model
    (scripts/solid_mug.py): seen up close, points are scattered dots. SOLID=0 keeps the points."""
    if solid_mug is None or os.environ.get("SOLID", "1") == "0" or not solid_mug.is_round_name(kind):
        return None, False
    try:
        if not solid_mug.fits_cylinder(points):
            log.info("%s does not look like a cylinder: kept as points", kind)
            return None, False
        return solid_mug.solid_glb(points, colours), True
    except Exception:                                 # a model of points is still a model
        log.exception("Could not make %s solid: kept as points", kind)
        return None, False


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
        glb, solid = _solid(kind, points, colours)
        model = models3d.save_scanned(kind, glb or photo_to_3d.glb_bytes(points, colours), size, MODELS_DIR)
        took = time.monotonic() - start
        log.info("Scanned %s from %d photo(s) in %.1f s: %d points%s, %s", kind, len(photos), took, len(points),
                 ", made solid" if solid else "", size)
        return {"name": kind, "model": model, "size": [round(v, 3) for v in size], "points": len(points), "solid": solid,
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
