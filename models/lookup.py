import json
import hashlib
import os
from pathlib import Path

BUILTIN_INDEX = Path(__file__).parent / "builtin" / "index.json"


def _get_cache_dir():
    return Path(os.environ.get("MODEL_CACHE_DIR", str(Path(__file__).parent / "cache")))


def _get_builtin_map():
    with open(BUILTIN_INDEX) as f:
        return json.load(f)


BUILTIN_MAP = _get_builtin_map()


def lookup(object_name: str):
    name = object_name.strip().lower()
    if not name:
        return None

    cache_dir = _get_cache_dir()
    cache_key = hashlib.md5(name.encode()).hexdigest()

    api_key = os.environ.get("SKETCHFAB_API_KEY")
    if api_key:
        from .sketchfab_client import download_model
        result = download_model(name, api_key, cache_dir, cache_key)
        if result:
            return (result, "sketchfab")

    for ext in [".glb", ".gltf"]:
        cached = cache_dir / f"{cache_key}{ext}"
        if cached.exists():
            return (str(cached), "cache")

    if name in BUILTIN_MAP:
        return (str(Path(__file__).parent / "builtin" / BUILTIN_MAP[name]), "builtin")

    return None
