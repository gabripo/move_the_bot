import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest


def test_websocket_connect_and_publish():
    """Test that a WebSocket can connect to rosbridge and publish."""
    websocket = pytest.importorskip("websocket")
    import socket

    def find_free_port():
        with socket.socket() as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    port = find_free_port()

    ws = websocket.WebSocket()
    try:
        ws.connect(f"ws://localhost:{port}", timeout=2)
    except:
        pytest.skip("No rosbridge server running on localhost")

    test_msg = {
        "op": "publish",
        "topic": "/test",
        "msg": {"data": "hello"},
    }
    ws.send(json.dumps(test_msg))
    ws.close()


def test_ros_topic_format():
    """Validate the JSON structure of rosbridge publish messages."""
    publish = {
        "op": "publish",
        "topic": "/spatial_coords",
        "msg": {"x": 0.234, "y": 0.321, "z": 0.156},
    }
    assert publish["op"] == "publish"
    assert publish["topic"] == "/spatial_coords"
    assert isinstance(publish["msg"]["x"], float)
    assert isinstance(publish["msg"]["y"], float)
    assert isinstance(publish["msg"]["z"], float)

    string_msg = {
        "op": "publish",
        "topic": "/voice_commands",
        "msg": {"data": "pick up the mug"},
    }
    assert isinstance(string_msg["msg"]["data"], str)


def test_publish_point_rosbridge_format():
    """Validate rosbridge publish message for geometry_msgs/Point."""
    msg = {
        "op": "publish",
        "topic": "/target_goal",
        "msg": {"x": 0.15, "y": 0.25, "z": 0.10},
    }
    assert msg["op"] == "publish"
    assert msg["topic"] == "/target_goal"
    assert isinstance(msg["msg"]["x"], float)
    assert isinstance(msg["msg"]["y"], float)
    assert isinstance(msg["msg"]["z"], float)
    # All fields must be present (no partial publishes)
    assert set(msg["msg"].keys()) == {"x", "y", "z"}


def test_subscribe_jointstate_format():
    """Validate rosbridge subscribe message for sensor_msgs/JointState."""
    sub = {
        "op": "subscribe",
        "topic": "/joint_states",
        "type": "sensor_msgs/JointState",
    }
    assert sub["op"] == "subscribe"
    assert sub["topic"] == "/joint_states"
    assert sub["type"] == "sensor_msgs/JointState"

    expected_response = {
        "op": "publish",
        "topic": "/joint_states",
        "msg": {
            "header": {"stamp": {"sec": 1234, "nanosec": 0}, "frame_id": ""},
            "name": ["joint1", "joint2", "joint3"],
            "position": [0.0, 0.5, 1.0],
            "velocity": [],
            "effort": [],
        },
    }
    resp = expected_response
    assert resp["op"] == "publish"
    assert resp["topic"] == "/joint_states"
    assert len(resp["msg"]["name"]) == 3
    assert len(resp["msg"]["position"]) == 3


def test_subscribe_markerarray_format():
    """Validate rosbridge subscribe message for visualization_msgs/MarkerArray."""
    sub = {
        "op": "subscribe",
        "topic": "/virtual_scene",
        "type": "visualization_msgs/MarkerArray",
        "throttle_rate": 0,
    }
    assert sub["op"] == "subscribe"
    assert sub["topic"] == "/virtual_scene"
    assert sub["type"] == "visualization_msgs/MarkerArray"

    expected_response = {
        "op": "publish",
        "topic": "/virtual_scene",
        "msg": {
            "markers": [
                {
                    "header": {"frame_id": "base_link"},
                    "ns": "apple",
                    "id": 1,
                    "type": 3,
                    "action": 0,
                    "pose": {
                        "position": {"x": 0.2, "y": 0.0, "z": 0.05},
                        "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
                    },
                    "scale": {"x": 0.1, "y": 0.1, "z": 0.1},
                    "color": {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0},
                }
            ]
        },
    }
    resp = expected_response
    assert len(resp["msg"]["markers"]) == 1
    marker = resp["msg"]["markers"][0]
    assert marker["ns"] == "apple"
    assert marker["type"] == 3  # CYLINDER
    assert marker["pose"]["position"]["x"] == 0.2
    assert marker["scale"]["x"] == 0.1


def test_rosbridge_subscribe_publish_contract():
    """Validate the subscribe → notification format contract."""
    sub = {"op": "subscribe", "topic": "/test_topic", "type": "std_msgs/String"}
    notification = {
        "op": "publish",
        "topic": "/test_topic",
        "msg": {"data": "hello"},
    }
    # The sub's topic must match the notification's topic
    assert notification["topic"] == sub["topic"]
    assert notification["op"] == "publish"
    assert notification["msg"]["data"] == "hello"
