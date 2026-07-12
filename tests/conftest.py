import os
import sys
import json
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import struct


@pytest.fixture
def ollama_mock():
    """HTTP server that returns canned JSON responses matching the fixture files."""
    import http.server
    import socketserver
    import json

    FIXTURES = Path(__file__).parent / "fixtures" / "ollama-mock"
    responses = {}
    for f in FIXTURES.glob("*.json"):
        with open(f) as fh:
            data = json.load(fh)
            responses[f.stem] = data

    class MockOllamaHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = responses.get("move", {"response": '{"action": "none"}'})
            self.wfile.write(json.dumps(resp).encode())

        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len).decode() if content_len else "{}"
            req = json.loads(body)
            prompt = req.get("prompt", "").lower()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if "grab" in prompt or "grasp" in prompt or "pick" in prompt:
                resp = responses.get("grasp", responses["grasp"])
            elif "release" in prompt or "drop" in prompt or "put" in prompt:
                resp = responses.get("release", responses["release"])
            elif "create" in prompt or "spawn" in prompt or "place" in prompt:
                resp = responses.get("spawn", responses["spawn"])
            elif "move" in prompt or "go" in prompt or "reach" in prompt:
                resp = responses.get("move", responses["move"])
            else:
                resp = responses.get("unknown", responses["unknown"])
            self.wfile.write(json.dumps(resp).encode())

        def log_message(self, format, *args):
            pass

    server = socketserver.TCPServer(("localhost", 0), MockOllamaHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    yield f"http://localhost:{port}/generate"
    server.shutdown()


@pytest.fixture
def model_cache_dir():
    with tempfile.TemporaryDirectory() as tmp:
        old = os.environ.get("MODEL_CACHE_DIR")
        os.environ["MODEL_CACHE_DIR"] = tmp
        yield Path(tmp)
        if old:
            os.environ["MODEL_CACHE_DIR"] = old
        else:
            del os.environ["MODEL_CACHE_DIR"]


@pytest.fixture
def builtin_index():
    import models.lookup as lookup
    return lookup.BUILTIN_MAP


@pytest.fixture
def minimal_glb():
    """Create a minimal valid GLB file for testing."""
    gltf = {
        "asset": {"version": "2.0", "generator": "test"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 3,
                "type": "VEC3",
                "max": [1, 1, 1],
                "min": [-1, -1, -1],
            },
            {
                "bufferView": 1,
                "componentType": 5123,
                "count": 3,
                "type": "SCALAR",
                "max": [2],
                "min": [0],
            },
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36, "target": 34962},
            {"buffer": 0, "byteOffset": 36, "byteLength": 6, "target": 34963},
        ],
        "buffers": [{"byteLength": 42}],
    }
    json_str = json.dumps(gltf, separators=(",", ":"))
    json_bytes = json_str.encode("ascii")
    json_pad = (4 - len(json_bytes) % 4) % 4

    vertices = struct.pack("<9f", -1, -1, 0, 1, -1, 0, 0, 1, 0)
    indices = struct.pack("<3H", 0, 1, 2)
    bin_data = vertices + indices
    bin_pad = (4 - len(bin_data) % 4) % 4

    tot_len = 12 + 8 + len(json_bytes) + json_pad + 8 + len(bin_data) + bin_pad
    glb = b"glTF"
    glb += struct.pack("<II", 2, tot_len)
    glb += struct.pack("<II", len(json_bytes) + json_pad, 0x4E4F534A)
    glb += json_bytes + b" " * json_pad
    glb += struct.pack("<II", len(bin_data) + bin_pad, 0x004E4942)
    glb += bin_data + b" " * bin_pad
    return glb
