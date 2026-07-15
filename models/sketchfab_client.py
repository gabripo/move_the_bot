import hashlib
import os
import requests
from pathlib import Path

SKETCHFAB_SEARCH = "https://api.sketchfab.com/v3/search"


def download_model(object_name: str, api_key: str, cache_dir: Path):
    headers = {"Authorization": f"Token {api_key}"}
    params = {
        "q": object_name,
        "type": "models",
        "sort_by": "-likeCount",
        "downloadable": "true",
        "archives_flavours": "glb",
    }

    try:
        resp = requests.get(SKETCHFAB_SEARCH, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"Sketchfab search error: {e}")
        return None

    results = resp.json().get("results", [])
    if not results:
        return None

    cache_key = hashlib.md5(object_name.encode()).hexdigest()
    local_path = cache_dir / f"{cache_key}.glb"

    for model in results:
        uid = model["uid"]
        try:
            dl_resp = requests.get(
                f"https://api.sketchfab.com/v3/models/{uid}/download",
                headers=headers,
                timeout=10,
            )
            dl_resp.raise_for_status()
            dl_data = dl_resp.json()
        except requests.RequestException:
            continue

        glb_url = dl_data.get("glb", {}).get("url")
        if not glb_url:
            continue

        try:
            with requests.get(glb_url, stream=True, timeout=30) as model_resp:
                model_resp.raise_for_status()
                content_length = int(model_resp.headers.get("content-length", 0))
                if content_length > 5 * 1024 * 1024:
                    print(f"Skipping {uid}: {content_length} bytes exceeds 5 MB limit")
                    continue
                with open(local_path, "wb") as f:
                    for chunk in model_resp.iter_content(chunk_size=8192):
                        f.write(chunk)
            return str(local_path)
        except requests.RequestException:
            continue

    return None
