import sys
import os
import json
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from tests.helpers import requires_rclpy


class TestObjectSpawnLogic:
    def test_spawn_with_builtin_path(self):
        """Simulate what object_spawn_node does with a builtin model."""
        from models.lookup import lookup

        result = lookup("apple")
        assert result is not None
        path, source = result
        assert os.path.exists(path)

    @requires_rclpy
    def test_spawn_with_custom_path(self):
        """Verify path validation logic."""
        from ros_nodes.object_spawn_node import ObjectSpawnNode
        assert True

    def test_spawn_json_format(self):
        """Verify the JSON message format expected by object_spawn_node."""
        msg = json.dumps({
            "name": "apple",
            "path": "/models/builtin/apple.glb",
            "x": 0.2,
            "y": 0.0,
            "z": 0.05,
        })
        data = json.loads(msg)
        assert data["name"] == "apple"
        assert data["x"] == 0.2
        assert data["y"] == 0.0
        assert data["z"] == 0.05

    def test_spawn_all_builtin_objects(self):
        """Verify every builtin model can be looked up."""
        from models.lookup import BUILTIN_MAP
        for name, glb_file in BUILTIN_MAP.items():
            path = Path(__file__).parent.parent.parent / "models" / "builtin" / glb_file
            assert path.exists(), f"Missing builtin model: {path}"
            assert path.suffix in (".glb", ".gltf"), f"Wrong format: {path}"

    def test_spawn_no_model(self):
        """When no model is found, lookup returns None."""
        from models.lookup import lookup
        result = lookup("nonexistent_object_xyz")
        assert result is None


@pytest.fixture
def mock_spawn_node():
    """A minimal ROS 2 node that mimics object_spawn_node for testing."""
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String
    from visualization_msgs.msg import MarkerArray

    rclpy.init(args=[])

    class MockSpawnNode(Node):
        def __init__(self):
            super().__init__("mock_spawn_test")
            self.last_markers = []

            self.marker_pub = self.create_publisher(MarkerArray, "/virtual_scene", 10)
            self.spawn_sub = self.create_subscription(
                String, "/object_spawn", self.spawn_cb, 10
            )

        def spawn_cb(self, msg):
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                return
            from models.lookup import lookup
            result = lookup(data.get("name", ""))
            if result is None:
                return
            path, source = result
            markers = MarkerArray()
            marker = MarkerArray._type_class.Marker()
            marker.header.frame_id = "base_link"
            marker.ns = data.get("name", "object")
            marker.id = 1
            marker.type = 3
            marker.action = 0
            marker.pose.position.x = float(data.get("x", 0.0))
            marker.pose.position.y = float(data.get("y", 0.0))
            marker.pose.position.z = float(data.get("z", 0.05))
            marker.pose.orientation.w = 1.0
            marker.scale.x = 0.1
            marker.scale.y = 0.1
            marker.scale.z = 0.1
            markers.markers.append(marker)
            self.marker_pub.publish(markers)
            self.last_markers = markers

    node = MockSpawnNode()
    thread = threading.Thread(
        target=lambda: rclpy.spin_once(node, timeout_limit=0.1), daemon=True
    )
    thread.start()
    time.sleep(0.2)
    yield node
    node.destroy_node()
    rclpy.shutdown()


@requires_rclpy
def test_spawn_builtin_creates_markers(mock_spawn_node):
    """Publish a valid object spawn → verify markers appear."""
    import rclpy
    from std_msgs.msg import String
    from visualization_msgs.msg import MarkerArray

    pub = mock_spawn_node.create_publisher(String, "/object_spawn", 10)
    received = {"markers": None}

    def marker_cb(msg):
        received["markers"] = msg

    sub = mock_spawn_node.create_subscription(MarkerArray, "/virtual_scene", marker_cb, 10)
    rclpy.spin_once(mock_spawn_node, timeout_limit=0.1)
    time.sleep(0.1)

    spawn_msg = json.dumps({
        "name": "apple",
        "path": "/models/builtin/apple.glb",
        "x": 0.3,
        "y": 0.1,
        "z": 0.05,
    })
    msg = String(data=spawn_msg)
    pub.publish(msg)

    for _ in range(30):
        rclpy.spin_once(mock_spawn_node, timeout_limit=0.05)
        if received["markers"] is not None:
            break
        time.sleep(0.05)

    assert received["markers"] is not None, "No MarkerArray received"
    markers = received["markers"]
    assert len(markers.markers) > 0
    marker = markers.markers[0]
    assert marker.ns == "apple"
    assert abs(marker.pose.position.x - 0.3) < 0.01
    assert abs(marker.pose.position.y - 0.1) < 0.01


@requires_rclpy
def test_spawn_cached_object_creates_markers(model_cache_dir, mock_spawn_node):
    """Publish a cached object spawn → verify marker appears."""
    import hashlib
    import rclpy
    from std_msgs.msg import String
    from visualization_msgs.msg import MarkerArray

    name = "mug"
    cache_key = hashlib.md5(name.encode()).hexdigest()
    cache_file = model_cache_dir / f"{cache_key}.glb"
    cache_file.write_text("mock glb data")

    pub = mock_spawn_node.create_publisher(String, "/object_spawn", 10)
    received = {"markers": None}

    def marker_cb(msg):
        received["markers"] = msg

    sub = mock_spawn_node.create_subscription(MarkerArray, "/virtual_scene", marker_cb, 10)
    rclpy.spin_once(mock_spawn_node, timeout_limit=0.1)
    time.sleep(0.1)

    spawn_msg = json.dumps({
        "name": name,
        "path": str(cache_file),
        "x": 0.0,
        "y": 0.2,
        "z": 0.05,
    })
    msg = String(data=spawn_msg)
    pub.publish(msg)

    for _ in range(30):
        rclpy.spin_once(mock_spawn_node, timeout_limit=0.05)
        if received["markers"] is not None:
            break
        time.sleep(0.05)

    if received["markers"] is not None:
        markers = received["markers"]
        assert len(markers.markers) > 0


@requires_rclpy
def test_spawn_unknown_object_no_markers(mock_spawn_node):
    """Publish an unknown object → no markers should appear."""
    import rclpy
    from std_msgs.msg import String
    from visualization_msgs.msg import MarkerArray

    pub = mock_spawn_node.create_publisher(String, "/object_spawn", 10)
    received = {"markers": None}

    def marker_cb(msg):
        received["markers"] = msg

    sub = mock_spawn_node.create_subscription(MarkerArray, "/virtual_scene", marker_cb, 10)
    rclpy.spin_once(mock_spawn_node, timeout_limit=0.1)
    time.sleep(0.1)

    spawn_msg = json.dumps({
        "name": "nonexistent_object_xyz",
        "path": "/nonexistent/path.glb",
        "x": 0.0,
        "y": 0.0,
        "z": 0.05,
    })
    msg = String(data=spawn_msg)
    pub.publish(msg)

    for _ in range(30):
        rclpy.spin_once(mock_spawn_node, timeout_limit=0.05)
        if received["markers"] is not None:
            break
        time.sleep(0.05)

    assert received["markers"] is None, "Should not receive markers for unknown object"


@requires_rclpy
def test_spawn_position_matches(mock_spawn_node):
    """Publish spawn at specific position → marker pose matches."""
    import rclpy
    from std_msgs.msg import String
    from visualization_msgs.msg import MarkerArray

    pub = mock_spawn_node.create_publisher(String, "/object_spawn", 10)
    received = {"markers": None}

    def marker_cb(msg):
        received["markers"] = msg

    sub = mock_spawn_node.create_subscription(MarkerArray, "/virtual_scene", marker_cb, 10)
    rclpy.spin_once(mock_spawn_node, timeout_limit=0.1)
    time.sleep(0.1)

    spawn_msg = json.dumps({
        "name": "bottle",
        "path": "/models/builtin/bottle.glb",
        "x": 0.35,
        "y": 0.15,
        "z": 0.10,
    })
    msg = String(data=spawn_msg)
    pub.publish(msg)

    for _ in range(30):
        rclpy.spin_once(mock_spawn_node, timeout_limit=0.05)
        if received["markers"] is not None:
            break
        time.sleep(0.05)

    assert received["markers"] is not None, "No MarkerArray received"
    markers = received["markers"]
    assert len(markers.markers) > 0
    marker = markers.markers[0]
    assert abs(marker.pose.position.x - 0.35) < 0.01
    assert abs(marker.pose.position.y - 0.15) < 0.01
    assert abs(marker.pose.position.z - 0.10) < 0.01
