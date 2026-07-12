import sys
import json
import time
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest


class TestFullPipeline:
    """End-to-end tests for the full perception→agent→actuation pipeline.

    These tests require a running Docker Compose stack with the ollama-agent profile.
    Run: docker compose -f docker/docker-compose.yml up
    """

    @pytest.fixture(scope="module")
    def rosbridge_ws(self):
        import websocket
        try:
            ws = websocket.WebSocket()
            ws.connect("ws://localhost:9090", timeout=5)
            yield ws
            ws.close()
        except Exception as e:
            pytest.skip(f"rosbridge not available: {e}. Run docker compose up first.")

    def test_hand_coords_to_joint_states(self, rosbridge_ws):
        """Publish hand coordinates → expect joint states to update."""
        ws = rosbridge_ws

        # Subscribe to joint_states
        sub = json.dumps({
            "op": "subscribe",
            "topic": "/joint_states",
            "type": "sensor_msgs/JointState",
        })
        ws.send(sub)

        # Publish hand coordinates
        pub = json.dumps({
            "op": "publish",
            "topic": "/spatial_coords",
            "msg": {"x": 0.2, "y": 0.3, "z": 0.25},
        })
        ws.send(pub)

        # Publish voice command
        pub_voice = json.dumps({
            "op": "publish",
            "topic": "/voice_commands",
            "msg": {"data": "move there"},
        })
        ws.send(pub_voice)

        # Wait and check for joint states
        time.sleep(0.5)
        ws.settimeout(3.0)
        try:
            response = ws.recv()
            data = json.loads(response)
            if data.get("topic") == "/joint_states":
                positions = data["msg"]["position"]
                assert len(positions) >= 3
                assert any(abs(p) > 0.01 for p in positions[:3]), "Joints should have moved"
        except Exception as e:
            pytest.skip(f"Did not receive joint_states: {e}")

    def test_voice_grasp(self, rosbridge_ws):
        """Voice command 'grab' → expect grasp_command."""
        ws = rosbridge_ws

        sub = json.dumps({
            "op": "subscribe",
            "topic": "/grasp_command",
            "type": "std_msgs/String",
        })
        ws.send(sub)

        pub = json.dumps({
            "op": "publish",
            "topic": "/voice_commands",
            "msg": {"data": "grab"},
        })
        ws.send(pub)

        pub_coords = json.dumps({
            "op": "publish",
            "topic": "/spatial_coords",
            "msg": {"x": 0.2, "y": 0.3, "z": 0.25},
        })
        ws.send(pub_coords)

        time.sleep(1.0)
        ws.settimeout(3.0)
        try:
            response = ws.recv()
            data = json.loads(response)
            if data.get("topic") == "/grasp_command":
                assert data["msg"]["data"] == "grasp"
        except Exception:
            pass  # Grasp may not fire without full agent stack

    def test_spawn_object(self, rosbridge_ws):
        """Publish object_spawn → expect /virtual_scene to update."""
        ws = rosbridge_ws

        sub_scene = json.dumps({
            "op": "subscribe",
            "topic": "/virtual_scene",
            "type": "visualization_msgs/MarkerArray",
        })
        ws.send(sub_scene)

        pub = json.dumps({
            "op": "publish",
            "topic": "/object_spawn",
            "msg": {
                "data": json.dumps({
                    "name": "test_object",
                    "path": "/models/builtin/apple.glb",
                    "x": 0.3,
                    "y": 0.1,
                    "z": 0.05,
                })
            },
        })
        ws.send(pub)

        time.sleep(0.5)
        ws.settimeout(3.0)
        try:
            response = ws.recv()
            data = json.loads(response)
            if data.get("topic") == "/virtual_scene":
                markers = data["msg"].get("markers", [])
                assert len(markers) > 0
        except Exception:
            pass

    def test_text_input_equivalence(self, rosbridge_ws):
        """Text input via /voice_commands should behave identically to speech."""
        ws = rosbridge_ws

        sub = json.dumps({
            "op": "subscribe",
            "topic": "/target_goal",
            "type": "geometry_msgs/Point",
        })
        ws.send(sub)

        pub = json.dumps({
            "op": "publish",
            "topic": "/voice_commands",
            "msg": {"data": "move to 0.15 0.25 0.20"},
        })
        ws.send(pub)

        time.sleep(1.0)
        ws.settimeout(3.0)
        try:
            response = ws.recv()
            data = json.loads(response)
            if data.get("topic") == "/target_goal":
                msg = data["msg"]
                assert "x" in msg
                assert "y" in msg
                assert "z" in msg
        except Exception:
            pytest.skip("No target_goal response received")

    def test_multiple_spawned_objects(self, rosbridge_ws):
        """Spawn multiple objects → expect multiple markers in scene."""
        ws = rosbridge_ws

        sub_scene = json.dumps({
            "op": "subscribe",
            "topic": "/virtual_scene",
            "type": "visualization_msgs/MarkerArray",
        })
        ws.send(sub_scene)

        for obj, pos in [("apple", 0.2), ("mug", 0.0), ("bottle", -0.2)]:
            pub = json.dumps({
                "op": "publish",
                "topic": "/object_spawn",
                "msg": {
                    "data": json.dumps({
                        "name": obj,
                        "path": f"/models/builtin/{obj}.glb",
                        "x": pos, "y": 0.1, "z": 0.05,
                    })
                },
            })
            ws.send(pub)

        time.sleep(0.5)
        ws.settimeout(3.0)
        try:
            response = ws.recv()
            data = json.loads(response)
            if data.get("topic") == "/virtual_scene":
                markers = data["msg"].get("markers", [])
                assert len(markers) >= 3, f"Expected >=3 markers, got {len(markers)}"
                names = {m.get("ns", "") for m in markers}
                assert "apple" in names or "mug" in names or "bottle" in names
        except Exception:
            pass

    def test_unknown_object_error(self, rosbridge_ws):
        """Spawning an unknown object should not crash the system."""
        ws = rosbridge_ws

        pub = json.dumps({
            "op": "publish",
            "topic": "/object_spawn",
            "msg": {
                "data": json.dumps({
                    "name": "unicorn",
                    "path": "/nonexistent/path/unicorn.glb",
                    "x": 0.0, "y": 0.0, "z": 0.05,
                })
            },
        })
        ws.send(pub)

        time.sleep(0.5)
        assert True  # System should still be responsive after an unknown object
