import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest


@pytest.fixture
def mock_rosbridge_server():
    import http.server
    import socketserver
    import json

    received = []

    class MockBridgeHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("Upgrade", "").lower() == "websocket":
                self.send_response(101)
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.end_headers()
            else:
                self.send_response(200)
                self.end_headers()

        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len) if content_len else b"{}"
            received.append(json.loads(body))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())

        def log_message(self, format, *args):
            pass

    server = socketserver.TCPServer(("localhost", 0), MockBridgeHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    yield f"ws://localhost:{port}", received
    server.shutdown()


class _WsEchoServer:
    """Minimal WebSocket echo server using raw sockets."""

    def __init__(self):
        import socket as sock_mod
        import struct
        import hashlib
        import base64
        import json

        self.received = []
        self._struct = struct
        self._hashlib = hashlib
        self._base64 = base64
        self._json = json
        self._stop = False
        self.port = None

        server = sock_mod.socket(sock_mod.AF_INET, sock_mod.SOCK_STREAM)
        server.setsockopt(sock_mod.SOL_SOCKET, sock_mod.SO_REUSEADDR, 1)
        server.bind(("localhost", 0))
        self.port = server.getsockname()[1]
        server.listen(5)
        server.settimeout(0.5)

        def decode_frame(data):
            if len(data) < 2:
                return None
            b1, b2 = data[0], data[1]
            opcode = b1 & 0x0F
            masked = (b2 & 0x80) != 0
            length = b2 & 0x7F
            offset = 2
            if length == 126:
                length = struct.unpack("!H", data[2:4])[0]
                offset = 4
            elif length == 127:
                length = struct.unpack("!Q", data[2:10])[0]
                offset = 10
            if masked:
                mask_key = data[offset:offset + 4]
                offset += 4
            payload = data[offset:offset + length]
            if masked:
                payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
            return payload.decode("utf-8")

        def handle(conn):
            key_val = None
            req = b""
            while b"\r\n\r\n" not in req:
                chunk = conn.recv(4096)
                if not chunk:
                    conn.close()
                    return
                req += chunk
            decoded = req.decode("utf-8", errors="replace")
            for line in decoded.split("\r\n"):
                if line.lower().startswith("sec-websocket-key:"):
                    key_val = line.split(":", 1)[1].strip()
                    break
            if not key_val:
                conn.close()
                return
            accept = base64.b64encode(
                hashlib.sha1((key_val + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
            ).decode()
            conn.sendall(
                b"HTTP/1.1 101 Switching Protocols\r\n"
                b"Upgrade: websocket\r\n"
                b"Connection: Upgrade\r\n"
                b"Sec-WebSocket-Accept: " + accept.encode() + b"\r\n"
                b"\r\n"
            )
            while not self._stop:
                try:
                    raw = conn.recv(8192)
                    if not raw:
                        break
                    text = decode_frame(raw)
                    if text is None:
                        break
                    parsed = json.loads(text)
                    self.received.append(parsed)
                except Exception:
                    break
            conn.close()

        def serve():
            while not self._stop:
                try:
                    conn, addr = server.accept()
                    t = threading.Thread(target=handle, args=(conn,), daemon=True)
                    t.start()
                except sock_mod.timeout:
                    continue
            server.close()

        self._thread = threading.Thread(target=serve, daemon=True)
        self._thread.start()
        time.sleep(0.2)

    def stop(self):
        self._stop = True
        self._thread.join(timeout=2)

    def url(self):
        return f"ws://localhost:{self.port}"


@pytest.fixture
def ws_echo_server():
    server = _WsEchoServer()
    yield server.url(), server.received
    server.stop()
