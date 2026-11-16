"""End-to-end test against the running robot stack (ROS 2 + ros2_control + MoveIt + agent).

Every motion here is really planned by MoveIt and executed by the arm controllers; only the
hardware underneath is simulated. Run inside the robot container:

    docker compose exec robot /ros_entrypoint.sh pytest -v /ros_ws/tests/e2e/test_robot.py
"""
import json
import math
import threading
import time
import uuid

import pytest

rclpy = pytest.importorskip("rclpy")
from geometry_msgs.msg import Point  # noqa: E402
from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from rclpy.node import Node  # noqa: E402
from rclpy.qos import DurabilityPolicy, QoSProfile  # noqa: E402
from sensor_msgs.msg import JointState  # noqa: E402
from std_msgs.msg import Bool, Float32, String  # noqa: E402

LIMITS = {   # from the URDF
    "shoulder_pan": (-1.92, 1.92), "shoulder_lift": (-1.75, 1.75), "elbow_flex": (-1.70, 1.70),
    "wrist_flex": (-1.66, 1.66), "wrist_roll": (-2.75, 2.85), "gripper": (-0.18, 1.75),
}


class Robot:
    """A thin test client: sends skills and commands, records what comes back."""

    def __init__(self):
        self.node = Node("e2e_test")
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.requests = self.node.create_publisher(String, "/skill/request", 20)
        self.commands = self.node.create_publisher(String, "/voice_commands", 20)
        self.teleop_enable = self.node.create_publisher(Bool, "/teleop/enable", 5)
        self.teleop_target = self.node.create_publisher(Point, "/teleop/target", 5)
        self.teleop_gripper = self.node.create_publisher(Float32, "/teleop/gripper", 5)
        self.results, self.state, self.agent, self.scene = {}, {}, {}, {"objects": []}
        self.log, self.joints, self.joint_extremes = [], {}, {}
        self.node.create_subscription(String, "/skill/status", self._on_status, 50)
        self.node.create_subscription(String, "/skill/state", lambda m: self.state.update(json.loads(m.data)), 5)
        self.node.create_subscription(String, "/agent/state", lambda m: self.agent.update(json.loads(m.data)), latched)
        self.node.create_subscription(String, "/scene/objects", lambda m: self.scene.update(json.loads(m.data)), latched)
        self.node.create_subscription(String, "/agent_log", lambda m: self.log.append(json.loads(m.data)), 100)
        self.node.create_subscription(JointState, "/joint_states", self._on_joints, 50)
        self.executor = SingleThreadedExecutor()
        self.executor.add_node(self.node)
        threading.Thread(target=self.executor.spin, daemon=True).start()

    def _on_status(self, msg):
        status = json.loads(msg.data)
        if status["state"] != "running":
            self.results[status["id"]] = status

    def _on_joints(self, msg):
        for name, position in zip(msg.name, msg.position):
            self.joints[name] = position
            low, high = self.joint_extremes.get(name, (position, position))
            self.joint_extremes[name] = (min(low, position), max(high, position))

    def wait(self, condition, timeout, what):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(0.05)
        raise AssertionError(f"timed out waiting for {what}")

    def skill(self, timeout=60.0, **request):
        request["id"] = uuid.uuid4().hex[:8]
        self.requests.publish(String(data=json.dumps(request)))
        self.wait(lambda: request["id"] in self.results, timeout, f"skill {request}")
        time.sleep(0.15)                      # let the scene and state messages arrive
        return self.results[request["id"]]

    def ok(self, **request):
        result = self.skill(**request)
        assert result["state"] == "succeeded", f"{request} -> {result}"
        return result

    def say(self, text, timeout=90.0):
        start = len(self.log)
        self.commands.publish(String(data=text))
        self.wait(lambda: any(e["role"] == "user" for e in self.log[start:]), 10, f"the agent to hear '{text}'")
        self.wait(lambda: not self.agent.get("busy"), timeout, f"the agent to finish '{text}'")
        time.sleep(0.3)
        return self.log[start:]

    def obj(self, name):
        return next((o for o in self.scene["objects"] if o["name"] == name), None)

    @property
    def tool(self):
        return self.state["tool"]


@pytest.fixture(scope="module")
def robot():
    rclpy.init()
    r = Robot()
    r.wait(lambda: r.state.get("ready"), 120, "MoveIt and the controllers")
    r.wait(lambda: len(r.joints) >= 6, 20, "joint states")
    r.wait(lambda: r.requests.get_subscription_count() > 0, 20, "the skill server")
    r.wait(lambda: r.commands.get_subscription_count() > 0, 30, "the agent")
    yield r
    r.skill(skill="reset")
    rclpy.shutdown()


@pytest.fixture(autouse=True)
def clean_table(robot):
    robot.teleop_enable.publish(Bool(data=False))
    robot.ok(skill="reset")
    assert robot.scene["objects"] == []


def near(a, b, tolerance=0.012):
    return math.dist(a, b) <= tolerance


# ------------------------------------------------------------------- skills

def test_starts_at_home_with_all_joints_reported(robot):
    assert set(LIMITS) <= set(robot.joints)
    assert robot.joints["shoulder_lift"] == pytest.approx(-0.79, abs=0.02)
    assert robot.state["holding"] is None and not robot.state["busy"]


def test_spawn_puts_objects_on_the_table(robot):
    robot.ok(skill="spawn", object="apple", at={"position": "center"})
    robot.ok(skill="spawn", object="red cube", at={"position": "left"})
    apple, cube = robot.obj("apple"), robot.obj("red cube")
    assert near(apple["position"][:2], (0.22, 0.0)) and apple["position"][2] == pytest.approx(0.0275)
    assert near(cube["position"][:2], (0.20, 0.13)) and cube["color"] == "#e53935"
    assert apple["model"] == "/models/builtin/apple.glb" and cube["model"] == ""


def test_pick_and_place_on_the_table(robot):
    robot.ok(skill="spawn", object="apple", at={"position": "center"})
    result = robot.ok(skill="pick", object="apple")
    assert "holding" in result["message"] and robot.state["holding"] == "apple"
    assert robot.obj("apple")["held"] and robot.obj("apple")["position"][2] > 0.06     # lifted
    robot.ok(skill="place", at={"position": "right"})
    apple = robot.obj("apple")
    assert robot.state["holding"] is None and not apple["held"]
    assert near(apple["position"], (0.20, -0.13, 0.0275))
    assert robot.joints["gripper"] > 0.5                                               # open again


def test_stack_one_object_on_another(robot):
    robot.ok(skill="spawn", object="cube", at={"position": "left"})
    robot.ok(skill="spawn", object="apple", at={"position": "right"})
    robot.ok(skill="pick", object="apple")
    robot.ok(skill="place", at={"object": "cube", "relation": "on"})
    apple, cube = robot.obj("apple"), robot.obj("cube")
    assert near(apple["position"][:2], cube["position"][:2])
    assert apple["position"][2] == pytest.approx(0.04 + 0.0275, abs=0.003)


def test_motion_into_an_obstacle_is_refused(robot):
    robot.ok(skill="spawn", object="can", at={"x": 0.22, "y": 0.0})
    result = robot.skill(skill="move_to", at={"x": 0.22, "y": 0.0, "z": 0.03})   # inside the can
    assert result["state"] == "failed" and "in the way" in result["message"]


def test_cannot_pick_from_under_another_object(robot):
    robot.ok(skill="spawn", object="cube", at={"position": "center"})
    robot.ok(skill="spawn", object="apple", at={"object": "cube", "relation": "on"})
    result = robot.skill(skill="pick", object="cube")
    assert result["state"] == "failed" and "on top" in result["message"]
    assert robot.state["holding"] is None


def test_readable_errors(robot):
    assert "no banana" in robot.skill(skill="pick", object="banana")["message"]
    assert "empty" in robot.skill(skill="place")["message"]
    assert robot.skill(skill="fly")["state"] == "failed"
    assert "cannot reach" in robot.skill(skill="move_to", at={"x": 0.55, "y": 0.0, "z": 0.30})["message"]


def test_one_object_at_a_time(robot):
    robot.ok(skill="spawn", object="apple", at={"position": "left"})
    robot.ok(skill="spawn", object="cube", at={"position": "right"})
    robot.ok(skill="pick", object="apple")
    result = robot.skill(skill="pick", object="cube")
    assert result["state"] == "failed" and "already holds" in result["message"]


def test_move_to_and_move_by(robot):
    robot.ok(skill="move_to", at={"x": 0.22, "y": 0.05, "z": 0.12})
    assert near(robot.tool, (0.22, 0.05, 0.12), 0.006)
    robot.ok(skill="move_by", dx=0.0, dy=-0.05, dz=0.04)
    assert near(robot.tool, (0.22, 0.0, 0.16), 0.008)
    robot.ok(skill="home")
    assert robot.joints["shoulder_lift"] == pytest.approx(-0.79, abs=0.02)


def test_plans_around_an_obstacle(robot):
    # A tall bottle between the start and the goal: the direct motion is blocked, so the
    # sampling planner has to find a way around. The request must still succeed.
    robot.ok(skill="move_to", at={"x": 0.2, "y": 0.16, "z": 0.05})
    robot.ok(skill="spawn", object="bottle", at={"x": 0.2, "y": 0.0})
    robot.ok(skill="move_to", at={"x": 0.2, "y": -0.16, "z": 0.05})
    assert near(robot.tool, (0.2, -0.16, 0.05), 0.008)
    assert near(robot.obj("bottle")["position"][:2], (0.2, 0.0), 0.001)                # untouched


def test_gripper_close_grabs_what_is_between_the_jaws(robot):
    robot.ok(skill="gripper", state="open")
    robot.ok(skill="move_to", at={"x": 0.245, "y": 0.0, "z": 0.025})
    time.sleep(0.5)
    x, y, _ = robot.state["jaws"]                                          # middle of the open jaws
    robot.ok(skill="spawn", object="cube", at={"x": x, "y": y})
    result = robot.ok(skill="gripper", state="close")
    assert "holding the cube" in result["message"]
    assert "released" in robot.ok(skill="gripper", state="open")["message"]


def test_stop_interrupts_a_motion(robot):
    robot.ok(skill="move_to", at={"x": 0.2, "y": 0.2, "z": 0.1})
    first = uuid.uuid4().hex[:8]
    robot.requests.publish(String(data=json.dumps(
        {"skill": "move_to", "at": {"x": 0.2, "y": -0.2, "z": 0.1}, "id": first})))
    robot.requests.publish(String(data=json.dumps({"skill": "home", "id": "queued"})))
    time.sleep(0.35)
    robot.skill(skill="stop")
    robot.wait(lambda: first in robot.results and "queued" in robot.results, 10, "the stop")
    assert robot.results[first]["state"] == "stopped"
    assert robot.results["queued"]["state"] == "stopped"
    assert robot.tool[1] > -0.19                                                       # never arrived
    robot.ok(skill="home")                                                             # still usable


def test_joints_stayed_inside_their_limits(robot):
    for name, (low, high) in LIMITS.items():
        seen_low, seen_high = robot.joint_extremes[name]
        assert seen_low >= low and seen_high <= high, f"{name} left its limits: {seen_low}..{seen_high}"


# -------------------------------------------------------------------- agent

def test_agent_understands_a_whole_sentence(robot):
    log = robot.say("create an apple and a red cube on the left, then put the apple on the cube")
    texts = [e["text"] for e in log]
    assert any("Understood by the rules" in t for t in texts)
    assert not any(e["role"] == "error" for e in log), texts
    apple, cube = robot.obj("apple"), robot.obj("red cube")
    assert near(apple["position"][:2], cube["position"][:2])
    assert apple["position"][2] > cube["position"][2]


def test_agent_follow_up_commands_use_context(robot):
    robot.say("create a mug")
    robot.say("grab it")
    assert robot.state["holding"] == "mug"
    robot.say("put it on the right")
    assert robot.state["holding"] is None and near(robot.obj("mug")["position"][:2], (0.20, -0.13))


def test_agent_puts_down_what_it_holds_before_picking_something_else(robot):
    robot.say("create an apple on the left and a cube on the right")
    robot.say("grab the apple")
    log = robot.say("grab the cube")
    assert robot.state["holding"] == "cube", [e["text"] for e in log]
    assert not robot.obj("apple")["held"]


def test_agent_reports_what_went_wrong(robot):
    log = robot.say("grab the banana")
    assert any(e["role"] == "error" and "no banana" in e["text"] for e in log)


def test_agent_stop_command(robot):
    robot.say("move to the left")
    robot.commands.publish(String(data="move to the right"))
    time.sleep(0.6)
    robot.say("stop")
    robot.wait(lambda: not robot.state["busy"], 10, "the robot to stop")
    assert robot.tool[1] > -0.12


# ------------------------------------------------------------ teleoperation

def _steer(robot, x, y, z, gripper, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        robot.teleop_target.publish(Point(x=x, y=y, z=z))
        robot.teleop_gripper.publish(Float32(data=gripper))
        time.sleep(1 / 15)


def test_hand_teleoperation_grabs_and_carries(robot):
    robot.ok(skill="spawn", object="cube", at={"x": 0.24, "y": 0.08})
    robot.teleop_enable.publish(Bool(data=True))
    robot.wait(lambda: robot.state.get("teleop"), 5, "teleoperation to switch on")
    _steer(robot, 0.24, 0.08, 0.12, 1.0, 2.0)
    assert near(robot.tool[:2], (0.24, 0.08), 0.06)                # the jaw centre is on the target
    _steer(robot, 0.24, 0.08, 0.03, 1.0, 2.0)
    _steer(robot, 0.24, 0.08, 0.03, 0.0, 1.5)                      # pinch
    assert robot.state["holding"] == "cube"
    _steer(robot, 0.18, -0.12, 0.15, 0.0, 3.0)                     # carry
    assert robot.obj("cube")["held"] and robot.obj("cube")["position"][2] > 0.08
    _steer(robot, 0.18, -0.12, 0.06, 0.0, 2.0)
    _steer(robot, 0.18, -0.12, 0.06, 1.0, 1.5)                     # open the hand
    cube = robot.obj("cube")
    assert robot.state["holding"] is None
    assert near(cube["position"], (0.18, -0.12, 0.02), 0.03)
    robot.teleop_enable.publish(Bool(data=False))
    robot.wait(lambda: not robot.state.get("teleop"), 5, "teleoperation to switch off")


def test_teleoperation_keeps_the_gripper_above_the_table(robot):
    robot.teleop_enable.publish(Bool(data=True))
    robot.wait(lambda: robot.state.get("teleop"), 5, "teleoperation to switch on")
    _steer(robot, 0.22, 0.0, -0.20, 1.0, 2.5)
    assert robot.tool[2] > 0.005
    _steer(robot, 0.90, 0.0, 0.10, 1.0, 2.5)                       # far outside the reach
    assert robot.tool[0] < 0.42
    robot.teleop_enable.publish(Bool(data=False))


def test_voice_command_works_during_teleoperation(robot):
    robot.teleop_enable.publish(Bool(data=True))
    _steer(robot, 0.25, 0.10, 0.10, 1.0, 1.5)
    robot.say("create an apple here")
    assert near(robot.obj("apple")["position"][:2], (0.25, 0.10), 0.02)
    robot.teleop_enable.publish(Bool(data=False))
