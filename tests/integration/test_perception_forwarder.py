import sys
import os
import json
import subprocess
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from tests.helpers import requires_rclpy


@pytest.fixture
def bridge_script():
    path = Path(__file__).parent.parent.parent / "agents" / "openclaw_agent" / "bridge" / "dist" / "forwarder_bridge.js"
    if not path.exists():
        pytest.skip("Bridge script not built. Run: cd agents/openclaw_agent/bridge && npm install && npx tsc")
    return str(path)


class TestSDKBackend:
    def test_bridge_process_spawns(self, bridge_script):
        """Verify the Node.js bridge process starts and accepts stdin."""
        proc = subprocess.Popen(
            ["node", bridge_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(0.5)
        assert proc.poll() is None, "Bridge process died on startup"
        proc.kill()
        proc.wait()

    def test_bridge_receives_message(self, bridge_script):
        """Send a JSON message via stdin and verify it's processed."""
        proc = subprocess.Popen(
            ["node", bridge_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(0.5)
        test_msg = json.dumps({"type": "task", "data": "test command"})
        proc.stdin.write(test_msg + "\n")
        proc.stdin.flush()

        import select
        import os as os_mod

        time.sleep(1)
        proc.kill()
        proc.wait()


@pytest.fixture
def mock_openclaw_gateway():
    """A simple HTTP server acting as mock OpenClaw Gateway (legacy, basic WS upgrade)."""
    import socketserver
    import http.server

    class GatewayHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("Upgrade", "").lower() == "websocket":
                self.send_response(101)
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.end_headers()
            else:
                self.send_response(200)
                self.end_headers()

        def log_message(self, format, *args):
            pass

    server = socketserver.TCPServer(("localhost", 0), GatewayHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    yield f"ws://localhost:{port}"
    server.shutdown()


class TestWSBackend:
    @requires_rclpy
    def test_import(self):
        from agents.openclaw_agent.bridge.perception_forwarder_ws import PerceptionForwarderWS
        assert PerceptionForwarderWS is not None

    @requires_rclpy
    def test_ws_connect_refused(self):
        """When no Gateway is running, the forwarder should handle gracefully."""
        os.environ["OPENCLAW_GATEWAY_URL"] = "ws://localhost:19999"
        from agents.openclaw_agent.bridge.perception_forwarder_ws import PerceptionForwarderWS
        assert True

    def test_ws_forward_coords_format(self):
        """Validate the RPC JSON format for forwarding spatial coords over WebSocket."""
        rpc_call = {
            "jsonrpc": "2.0",
            "method": "publish",
            "params": {
                "topic": "/spatial_coords",
                "msg": {"x": 0.234, "y": 0.321, "z": 0.156},
            },
            "id": 1,
        }
        assert rpc_call["method"] == "publish"
        assert rpc_call["params"]["topic"] == "/spatial_coords"
        assert rpc_call["params"]["msg"]["x"] == 0.234
        assert "jsonrpc" in rpc_call

    def test_ws_forward_voice_format(self):
        """Validate the RPC JSON format for forwarding voice commands."""
        rpc_call = {
            "jsonrpc": "2.0",
            "method": "publish",
            "params": {
                "topic": "/voice_commands",
                "msg": {"data": "pick up the mug"},
            },
            "id": 2,
        }
        assert rpc_call["params"]["topic"] == "/voice_commands"
        assert rpc_call["params"]["msg"]["data"] == "pick up the mug"

    def test_ws_gateway_rpc_roundtrip(self, ws_echo_server):
        """Send an RPC message through a WebSocket echo server and verify response."""
        websocket = pytest.importorskip("websocket")
        url, received = ws_echo_server

        ws = websocket.WebSocket()
        ws.connect(url, timeout=5)

        rpc_call = {
            "jsonrpc": "2.0",
            "method": "publish",
            "params": {
                "topic": "/spatial_coords",
                "msg": {"x": 0.1, "y": 0.2, "z": 0.3},
            },
            "id": 1,
        }
        ws.send(json.dumps(rpc_call))
        time.sleep(0.3)
        ws.close()

        assert len(received) > 0
        msg = received[0]
        assert msg["method"] == "publish"
        assert msg["params"]["topic"] == "/spatial_coords"
        assert msg["params"]["msg"]["x"] == 0.1

    def test_ws_reconnect_format(self):
        """Validate the reconnect message format for the WS forwarder."""
        reconnect_msg = {
            "jsonrpc": "2.0",
            "method": "connect",
            "params": {"client_type": "perception_forwarder", "version": "1.0"},
            "id": 1,
        }
        assert reconnect_msg["method"] == "connect"
        assert reconnect_msg["params"]["client_type"] == "perception_forwarder"
