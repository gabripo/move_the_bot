"""Find a 3D model (GLB file) to draw an object with.

Order: your own models (models/local, never committed) and objects scanned with the webcam (the
optional scanner, see docker/scan_server.py), the newer of the two first, so a new scan replaces
your own model and copying a model in replaces an old scan; then the models shipped with the repo, then the download
cache, then Sketchfab (only when a SKETCHFAB_API_KEY is set). When nothing is found the browser draws the basic shape instead, so
a missing model never blocks the robot.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import requests

SKETCHFAB_SEARCH = "https://api.sketchfab.com/v3/search"
MAX_BYTES = 5 * 1024 * 1024


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _name_score(query: str, model_name: str) -> int:
    """How well a Sketchfab model title matches the requested object (higher is better)."""
    q, n = query.strip().lower(), model_name.strip().lower()
    if n == q:
        return 100
    words = re.split(r"[\s\-_]+", n)
    if q not in words:
        return 5 if q in n else 0
    extra = len(words) - 1
    return max(90 - extra * 5, 40) if words[-1] == q else max(70 - extra * 5, 20)


def _download(model: dict, headers: dict, target: Path) -> bool:
    try:
        info = requests.get(f"https://api.sketchfab.com/v3/models/{model['uid']}/download",
                            headers=headers, timeout=10)
        info.raise_for_status()
        url = (info.json().get("glb") or {}).get("url")
        if not url:
            return False
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            if int(r.headers.get("content-length", 0)) > MAX_BYTES:
                return False
            size, partial = 0, target.with_suffix(".part")
            with open(partial, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        partial.unlink(missing_ok=True)
                        return False
                    f.write(chunk)
            partial.rename(target)
        return True
    except (requests.RequestException, OSError, ValueError, KeyError):
        return False


def _from_sketchfab(name: str, api_key: str, target: Path) -> bool:
    headers = {"Authorization": f"Token {api_key}"}
    try:
        r = requests.get(SKETCHFAB_SEARCH, headers=headers, timeout=10, params={
            "q": name, "type": "models", "sort_by": "relevance", "downloadable": "true",
            "archives_flavours": "glb", "count": 24})
        r.raise_for_status()
        results = r.json().get("results", [])
    except (requests.RequestException, ValueError):
        return False
    ranked = sorted(results, key=lambda m: (-_name_score(name, m.get("name", "")), len(m.get("name", ""))))
    for model in ranked[:8]:
        if _name_score(name, model.get("name", "")) == 0:
            break
        if _download(model, headers, target):
            return True
    return False


def cache_file(kind: str, models_dir: str) -> Path:
    """Where the model of `kind` is kept in the cache (downloaded or scanned)."""
    return Path(models_dir) / "cache" / f"{_slug(kind)}_{hashlib.md5(kind.encode()).hexdigest()[:8]}.glb"


def save_scanned(kind: str, glb: bytes, size, models_dir: str) -> str:
    """Keep a model made from a webcam photo, with the real size of the object (metres:
    width, depth, height). From now on 'create a <kind>' uses it. Returns its web path."""
    target = cache_file(kind, models_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    partial.write_bytes(glb)
    partial.rename(target)
    target.with_suffix(".json").write_text(json.dumps(
        {"kind": kind, "size": [round(float(v), 4) for v in size], "source": "scan"}))
    return f"/models/cache/{target.name}"


def scanned_size(kind: str, models_dir: str):
    """The size (metres) of a scanned object, or None if `kind` was not scanned."""
    try:
        info = json.loads(cache_file(kind, models_dir).with_suffix(".json").read_text())
        size = tuple(float(v) for v in info["size"])
        return size if len(size) == 3 and all(0.005 <= v <= 0.5 for v in size) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def scanned_kinds(models_dir: str) -> list:
    """The names of all objects scanned with the webcam."""
    kinds = []
    for f in (Path(models_dir) / "cache").glob("*.json"):
        try:
            info = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if info.get("source") == "scan" and info.get("kind") and f.with_suffix(".glb").is_file():
            kinds.append(info["kind"])
    return kinds


def find_model(kind: str, models_dir: str, allow_download: bool = True) -> str:
    """Web path of a GLB for `kind` ('/models/builtin/apple.glb'), or '' when there is none."""
    slug = _slug(kind)
    if not slug:
        return ""
    root = Path(models_dir)
    cached = cache_file(kind, models_dir)
    scanned = cached.is_file() and scanned_size(kind, models_dir) is not None
    own = root / "local" / f"{slug}.glb"
    if own.is_file() and not (scanned and cached.stat().st_mtime > own.stat().st_mtime):
        return f"/models/local/{slug}.glb"
    if scanned:                               # your own scan beats the repo's model; a newer one, yours too
        return f"/models/cache/{cached.name}"
    if (root / "builtin" / f"{slug}.glb").is_file():
        return f"/models/builtin/{slug}.glb"
    if cached.is_file() and cached.stat().st_size > 0:
        return f"/models/cache/{cached.name}"
    api_key = os.environ.get("SKETCHFAB_API_KEY", "").strip()
    if allow_download and api_key:
        try:
            cached.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return ""
        if _from_sketchfab(kind, api_key, cached):
            return f"/models/cache/{cached.name}"
    return ""


def clear_cache(models_dir: str) -> int:
    count = 0
    for f in (Path(models_dir) / "cache").glob("*.glb"):
        try:
            f.unlink()
            f.with_suffix(".json").unlink(missing_ok=True)      # the size of a scanned object
            count += 1
        except OSError:
            pass
    return count
