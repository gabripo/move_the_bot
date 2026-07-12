import sys
import os
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from models.lookup import lookup


def test_builtin_hit():
    result = lookup("apple")
    assert result is not None
    path, source = result
    assert source == "builtin"
    assert path.endswith(".glb")


def test_builtin_case_insensitive():
    result = lookup("Apple")
    assert result is not None
    path, source = result
    assert source == "builtin"


def test_builtin_alias():
    result = lookup("coffee mug")
    assert result is not None
    path, source = result
    assert source == "builtin"
    assert "mug" in path


def test_builtin_alias_ball():
    result = lookup("ball")
    assert result is not None
    path, source = result
    assert "sphere" in path


def test_unknown_object():
    result = lookup("xyznonexistent999")
    assert result is None


def test_empty_string():
    result = lookup("")
    assert result is None


def test_cache_hit(model_cache_dir):
    import hashlib
    name = "unicorn"
    cache_key = hashlib.md5(name.encode()).hexdigest()
    cache_file = model_cache_dir / f"{cache_key}.glb"
    cache_file.write_text("mock glb data")
    result = lookup(name)
    assert result is not None
    path, source = result
    assert source == "cache"


def test_all_builtin_entries():
    from models.lookup import BUILTIN_MAP
    for name in BUILTIN_MAP:
        result = lookup(name)
        assert result is not None, f"Builtin '{name}' should be found"
        path, source = result
        assert source == "builtin"
        assert os.path.exists(path), f"GLB file for '{name}' not found at {path}"


def test_sketchfab_hit_mocked(monkeypatch, model_cache_dir):
    """Simulate a Sketchfab download with mock API."""
    monkeypatch.setenv("SKETCHFAB_API_KEY", "mock_key_12345")

    class MockResponse:
        status_code = 200

        def json(self):
            if "search" in self._url:
                return {"results": [{"uid": "abc123"}]}
            elif "download" in self._url:
                return {"glb": {"url": "https://example.com/model.glb"}}
            else:
                return b"mock glb content"

        def raise_for_status(self):
            pass

        def __init__(self, url, **kwargs):
            self._url = url

        @property
        def content(self):
            return b"mock glb content"

    import requests
    monkeypatch.setattr(requests, "get", lambda url, **kw: MockResponse(url, **kw))

    result = lookup("teapot")
    assert result is not None, "Sketchfab lookup should return a path"
    path, source = result
    assert source == "sketchfab"
    assert os.path.exists(path)


def test_sketchfab_no_results_mocked(monkeypatch, model_cache_dir):
    """When Sketchfab returns no results, lookup returns None."""
    monkeypatch.setenv("SKETCHFAB_API_KEY", "mock_key_12345")

    class MockEmptyResponse:
        status_code = 200

        def json(self):
            return {"results": []}

        def raise_for_status(self):
            pass

    import requests
    monkeypatch.setattr(requests, "get", lambda url, **kw: MockEmptyResponse())

    result = lookup("xyznonexistent123")
    assert result is None


def test_sketchfab_no_api_key(monkeypatch, model_cache_dir):
    """Without SKETCHFAB_API_KEY, lookup never calls Sketchfab."""
    monkeypatch.delenv("SKETCHFAB_API_KEY", raising=False)

    import requests
    called = []

    def track_call(url, **kw):
        called.append(url)
        raise Exception("should not be called")

    monkeypatch.setattr(requests, "get", track_call)

    result = lookup("teapot")
    assert result is None
    assert len(called) == 0, "requests.get should not be called without API key"
