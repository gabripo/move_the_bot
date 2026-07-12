import sys
import json
import time
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from tests.helpers import requires_rclpy


@pytest.fixture
def mock_agent_node():
    """A minimal ROS 2 node that echoes /spatial_coords + /voice_commands
    to /target_goal and /grasp_command for testing."""
    import rclpy
    from rclpy.node import Node
    from geometry_msgs.msg import Point
    from std_msgs.msg import String

    rclpy.init(args=[])

    class MockAgent(Node):
        def __init__(self):
            super().__init__("mock_agent")
            self.last_goal = None
            self.last_grasp = None
            self.last_spawn = None

            self.goal_pub = self.create_publisher(Point, "/target_goal", 10)
            self.grasp_pub = self.create_publisher(String, "/grasp_command", 10)
            self.spawn_pub = self.create_publisher(String, "/object_spawn", 10)

            self.coords_sub = self.create_subscription(
                Point, "/spatial_coords", self.coords_cb, 10
            )
            self.voice_sub = self.create_subscription(
                String, "/voice_commands", self.voice_cb, 10
            )

        def coords_cb(self, msg):
            goal = Point()
            goal.x = msg.x
            goal.y = msg.y
            goal.z = msg.z
            self.goal_pub.publish(goal)
            self.last_goal = (msg.x, msg.y, msg.z)

        def voice_cb(self, msg):
            text = msg.data.lower()
            if "grab" in text or "grasp" in text or "pick" in text:
                s = String()
                s.data = "grasp"
                self.grasp_pub.publish(s)
                self.last_grasp = "grasp"
            elif "release" in text or "drop" in text or "put" in text:
                s = String()
                s.data = "release"
                self.grasp_pub.publish(s)
                self.last_grasp = "release"
            elif "create" in text or "spawn" in text or "place" in text:
                spawn_data = json.dumps({
                    "name": "apple",
                    "path": "/models/builtin/apple.glb",
                    "x": 0.2, "y": 0.0, "z": 0.05,
                })
                s = String()
                s.data = spawn_data
                self.spawn_pub.publish(s)
                self.last_spawn = spawn_data

    node = MockAgent()
    thread = threading.Thread(target=lambda: rclpy.spin_once(node, timeout_limit=0.1), daemon=True)
    thread.start()
    time.sleep(0.2)
    yield node
    node.destroy_node()
    rclpy.shutdown()


@requires_rclpy
def test_hand_coords_to_target_goal(mock_agent_node):
    """Publish /spatial_coords → agent → /target_goal updated."""
    import rclpy
    from geometry_msgs.msg import Point
    from std_msgs.msg import String

    pub = mock_agent_node.create_publisher(Point, "/spatial_coords", 10)
    received = {"goal": None}

    def goal_cb(msg):
        received["goal"] = (msg.x, msg.y, msg.z)

    sub = mock_agent_node.create_subscription(Point, "/target_goal", goal_cb, 10)
    rclpy.spin_once(mock_agent_node, timeout_limit=0.1)
    time.sleep(0.1)

    msg = Point(x=0.25, y=0.15, z=0.30)
    pub.publish(msg)

    for _ in range(20):
        rclpy.spin_once(mock_agent_node, timeout_limit=0.05)
        if received["goal"] is not None:
            break
        time.sleep(0.05)

    assert received["goal"] is not None, "No /target_goal received"
    x, y, z = received["goal"]
    assert abs(x - 0.25) < 0.01
    assert abs(y - 0.15) < 0.01
    assert abs(z - 0.30) < 0.01


@requires_rclpy
def test_voice_grasp_command(mock_agent_node):
    """Publish 'grab' → /grasp_command == 'grasp'."""
    import rclpy
    from std_msgs.msg import String

    pub = mock_agent_node.create_publisher(String, "/voice_commands", 10)
    received = {"grasp": None}

    def grasp_cb(msg):
        received["grasp"] = msg.data

    sub = mock_agent_node.create_subscription(String, "/grasp_command", grasp_cb, 10)
    rclpy.spin_once(mock_agent_node, timeout_limit=0.1)
    time.sleep(0.1)

    msg = String(data="grab the apple")
    pub.publish(msg)

    for _ in range(20):
        rclpy.spin_once(mock_agent_node, timeout_limit=0.05)
        if received["grasp"] is not None:
            break
        time.sleep(0.05)

    assert received["grasp"] == "grasp"


@requires_rclpy
def test_voice_release_command(mock_agent_node):
    """Publish 'release' → /grasp_command == 'release'."""
    import rclpy
    from std_msgs.msg import String

    pub = mock_agent_node.create_publisher(String, "/voice_commands", 10)
    received = {"grasp": None}

    def grasp_cb(msg):
        received["grasp"] = msg.data

    sub = mock_agent_node.create_subscription(String, "/grasp_command", grasp_cb, 10)
    rclpy.spin_once(mock_agent_node, timeout_limit=0.1)
    time.sleep(0.1)

    msg = String(data="release the object")
    pub.publish(msg)

    for _ in range(20):
        rclpy.spin_once(mock_agent_node, timeout_limit=0.05)
        if received["grasp"] is not None:
            break
        time.sleep(0.05)

    assert received["grasp"] == "release"


@requires_rclpy
def test_voice_spawn_object(mock_agent_node):
    """Publish 'create apple at middle' → /object_spawn with valid JSON."""
    import rclpy
    from std_msgs.msg import String

    pub = mock_agent_node.create_publisher(String, "/voice_commands", 10)
    received = {"spawn": None}

    def spawn_cb(msg):
        received["spawn"] = msg.data

    sub = mock_agent_node.create_subscription(String, "/object_spawn", spawn_cb, 10)
    rclpy.spin_once(mock_agent_node, timeout_limit=0.1)
    time.sleep(0.1)

    msg = String(data="create apple at middle")
    pub.publish(msg)

    for _ in range(20):
        rclpy.spin_once(mock_agent_node, timeout_limit=0.05)
        if received["spawn"] is not None:
            break
        time.sleep(0.05)

    assert received["spawn"] is not None, "No /object_spawn received"
    data = json.loads(received["spawn"])
    assert data["name"] == "apple"
    assert "x" in data
    assert "y" in data
    assert "z" in data


@requires_rclpy
def test_unreachable_target_no_goal(mock_agent_node):
    """Far-away hand coords should not produce movement beyond limits."""
    import rclpy
    from geometry_msgs.msg import Point

    pub = mock_agent_node.create_publisher(Point, "/spatial_coords", 10)
    received = {"goal": None}

    def goal_cb(msg):
        received["goal"] = (msg.x, msg.y, msg.z)

    sub = mock_agent_node.create_subscription(Point, "/target_goal", goal_cb, 10)
    rclpy.spin_once(mock_agent_node, timeout_limit=0.1)
    time.sleep(0.1)

    msg = Point(x=5.0, y=5.0, z=5.0)
    pub.publish(msg)

    for _ in range(20):
        rclpy.spin_once(mock_agent_node, timeout_limit=0.05)
        if received["goal"] is not None:
            break
        time.sleep(0.05)

    if received["goal"] is not None:
        x, y, z = received["goal"]
        assert -0.5 <= x <= 0.5, f"Goal x={x} out of workspace"
        assert 0.0 <= y <= 0.5, f"Goal y={y} out of workspace"
        assert 0.0 <= z <= 0.5, f"Goal z={z} out of workspace"
