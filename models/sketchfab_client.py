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
            model_resp = requests.get(glb_url, timeout=30)
            model_resp.raise_for_status()
            with open(local_path, "wb") as f:
                f.write(model_resp.content)
            return str(local_path)
        except requests.RequestException:
            continue

    return None
