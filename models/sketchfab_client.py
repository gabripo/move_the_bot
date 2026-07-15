import hashlib
import os
import requests
from pathlib import Path

SKETCHFAB_SEARCH = "https://api.sketchfab.com/v3/search"


def _name_score(query: str, model_name: str) -> int:
    q = query.strip().lower()
    n = model_name.strip().lower()

    if n == q:
        return 100
    words = n.split()
    if q not in words:
        if q in n.replace("-", " ").replace("_", " "):
            return 5
        return 0

    idx = words.index(q)
    extra = len(words) - 1
    if idx == len(words) - 1:
        return max(90 - extra * 5, 40)
    return max(70 - extra * 5, 20)


def _is_name_close(query: str, model_name: str) -> bool:
    q = query.strip().lower()
    n = model_name.strip().lower()
    if n == q:
        return True
    words = n.split()
    return bool(words) and words[-1] == q


def _try_download(model: dict, headers: dict, local_path: Path) -> str | None:
    uid = model["uid"]
    name = model.get("name", "?")
    try:
        dl_resp = requests.get(
            f"https://api.sketchfab.com/v3/models/{uid}/download",
            headers=headers,
            timeout=10,
        )
        dl_resp.raise_for_status()
        dl_data = dl_resp.json()
    except requests.RequestException:
        print(f"  Skip {name} ({uid[:12]}): download not available")
        return None

    glb_url = dl_data.get("glb", {}).get("url")
    if not glb_url:
        print(f"  Skip {name} ({uid[:12]}): no GLB archive")
        return None

    try:
        with requests.get(glb_url, stream=True, timeout=30) as model_resp:
            model_resp.raise_for_status()
            content_length = int(model_resp.headers.get("content-length", 0))
            if content_length > 5 * 1024 * 1024:
                print(f"  Skip {name} ({uid[:12]}): {content_length} bytes exceeds 5 MB limit")
                return None
            with open(local_path, "wb") as f:
                for chunk in model_resp.iter_content(chunk_size=8192):
                    f.write(chunk)
        print(f"Downloaded {name}")
        return str(local_path)
    except requests.RequestException:
        print(f"  Skip {name} ({uid[:12]}): download failed")
        return None



def _search(headers: dict, params: dict) -> list[dict]:
    try:
        resp = requests.get(SKETCHFAB_SEARCH, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json().get("results", [])
    except requests.RequestException as e:
        print(f"Sketchfab search error: {e}")
        return []


def download_model(object_name: str, api_key: str, cache_dir: Path, cache_key: str | None = None):
    headers = {"Authorization": f"Token {api_key}"}
    if cache_key is None:
        cache_key = hashlib.md5(object_name.encode()).hexdigest()
    local_path = cache_dir / f"{cache_key}.glb"

    # ── Pass 1: restricted search (downloadable GLB only) ──────────────
    results = _search(headers, {
        "q": object_name, "type": "models", "sort_by": "relevance",
        "downloadable": "true", "archives_flavours": "glb", "count": 50,
    })

    if results:
        first_name = results[0].get("name", "")
        if _is_name_close(object_name, first_name):
            for model in results:
                r = _try_download(model, headers, local_path)
                if r:
                    return r
        else:
            print(f"First result '{first_name}' differs from query '{object_name}', fallback to name scoring")
            scored = [(m, _name_score(object_name, m.get("name", "")), m.get("name", "")) for m in results]
            scored.sort(key=lambda x: (-x[1], len(x[2])))
            for model, score, _name in scored:
                r = _try_download(model, headers, local_path)
                if r:
                    return r

    # ── Pass 2: relaxed search (any model, filter at download time) ───
    relax_results = _search(headers, {
        "q": object_name, "type": "models", "sort_by": "relevance", "count": 100,
    })
    seen_uids = {m["uid"] for m in results}
    new_models = [m for m in relax_results if m["uid"] not in seen_uids]
    if new_models:
        print(f"Relaxed search found {len(new_models)} additional candidates")
        scored = [(m, _name_score(object_name, m.get("name", ""))) for m in new_models]
        scored.sort(key=lambda x: (-x[1], len(x[2])))
        for model, score in scored:
            r = _try_download(model, headers, local_path)
            if r:
                return r

    return None
