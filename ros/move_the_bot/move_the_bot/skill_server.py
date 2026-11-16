"""The skill server: turns skill requests into robot motion.

  /skill/request  (std_msgs/String, JSON)   {"id": "7", "skill": "pick", "object": "apple"}
  /skill/status   (std_msgs/String, JSON)   {"id": "7", "state": "running" | "succeeded" | "failed" | "stopped", "message": "..."}
  /skill/state    (std_msgs/String, JSON)   busy / holding / teleop / tool position, 5 times a second
  /scene/objects  (std_msgs/String, JSON)   every object on the table, for the browser

Arm motions are planned and executed by MoveIt 2 (`/move_action`), which sends the trajectory
to ros2_control. This node never talks to hardware itself, so the same code drives the mock
arm, Isaac Sim or a real SO-101.

Hand teleoperation (`/teleop/*`) streams small joint targets straight to the arm controller.
"""
from __future__ import annotations

import json
import math
import queue
import threading
import time

import numpy as np
import rclpy
from control_msgs.action import FollowJointTrajectory
from geometry_msgs.msg import Point, Pose
from moveit_msgs.action import MoveGroup
from moveit_msgs.msg import (AttachedCollisionObject, CollisionObject, Constraints,
                             JointConstraint, MoveItErrorCodes, PlanningScene)
from moveit_msgs.srv import ApplyPlanningScene
from rclpy.action import ActionClient
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from sensor_msgs.msg import JointState
from shape_msgs.msg import SolidPrimitive
from std_msgs.msg import Bool, Float32, String
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

from . import models3d
from .kinematics import PITCHES, Chain
from .skills import describe, validate
from .world import CATALOGUE, COLORS, MAX_GRASP_WIDTH, World, canonical_kind

BASE_FRAME = "base_link"
TOOL_LINK = "gripper_frame_link"
ARM_GROUP = "arm"
GRIPPER_JOINT = "gripper"
HOME = [0.0, -0.79, 0.31, 1.52, 0.0]
GRIPPER_TOUCH_LINKS = ["gripper_link", "moving_jaw_so101_v1_link", "gripper_frame_link"]

APPROACH = 0.07          # how far above an object the gripper stops before going down
HOVER = 0.10             # height for "move to the left" style commands
SHRINK = 0.006           # collision shapes are this much smaller, so resting contact is not a hit
GRIPPER_OPEN = 1.0
GRIPPER_CLOSED = -0.15
TELEOP_RATE = 15.0       # Hz
TELEOP_MAX_STEP = 0.03   # metres per tick (0.45 m/s)

# Planners, in the order they are tried: a smooth direct motion first; if something is in the
# way, a sampling planner that finds a path around it.
PIPELINES = (("pilz_industrial_motion_planner", "PTP"), ("ompl", "RRTConnect"))

ERROR_TEXT = {
    MoveItErrorCodes.PLANNING_FAILED: "no path found",
    MoveItErrorCodes.INVALID_MOTION_PLAN: "something is in the way",
    MoveItErrorCodes.CONTROL_FAILED: "the controller could not follow the path",
    MoveItErrorCodes.TIMED_OUT: "planning timed out",
    MoveItErrorCodes.PREEMPTED: "stopped",
    MoveItErrorCodes.START_STATE_IN_COLLISION: "the arm is touching something at the start",
    MoveItErrorCodes.GOAL_IN_COLLISION: "the target would collide with something",
    MoveItErrorCodes.INVALID_GOAL_CONSTRAINTS: "the target is outside the joint limits",
    MoveItErrorCodes.FAILURE: "something is in the way",
}


class SkillError(Exception):
    """A skill could not be carried out; the message is shown to the user."""


class Stopped(Exception):
    """The user asked to stop."""


def gripper_angle(width: float) -> float:
    """Gripper joint angle for a jaw opening in metres (fitted to the SO-101 jaw geometry)."""
    return max(GRIPPER_CLOSED, min(1.6, (width - 0.0162) / 0.074))


class SkillServer(Node):
    def __init__(self):
        super().__init__("skill_server")
        self.declare_parameter("robot_description", "")
        self.declare_parameter("models_dir", "/models")
        urdf = self.get_parameter("robot_description").value
        if not urdf:
            raise RuntimeError("skill_server needs the robot_description parameter")
        self.models_dir = self.get_parameter("models_dir").value
        self.chain = Chain.from_urdf(urdf, BASE_FRAME, TOOL_LINK)
        self.arm_joints = self.chain.joint_names

        self.world = World()
        self.lock = threading.RLock()
        self.joints = {}                    # latest joint positions by name
        self.requests = queue.Queue()
        self.busy = False
        self.current = None                 # request being executed
        self.stop_flag = threading.Event()
        self.goal_handle = None
        self.grip_height = 0.03             # tool height above the held object's bottom
        self.grip_width = 0.0

        self.teleop = False
        self.teleop_target = None
        self.teleop_target_time = 0.0
        self.teleop_tip = None
        self.teleop_q = None
        self.teleop_gripper = None
        self.hand = None                    # last hand position, for "put it here"
        self._teleop_restart = True

        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.status_pub = self.create_publisher(String, "/skill/status", 20)
        self.state_pub = self.create_publisher(String, "/skill/state", 5)
        self.scene_pub = self.create_publisher(String, "/scene/objects", latched)
        self.arm_pub = self.create_publisher(JointTrajectory, "/arm_controller/joint_trajectory", 5)
        self.gripper_pub = self.create_publisher(JointTrajectory, "/gripper_controller/joint_trajectory", 5)

        # Every callback here is short. Work that blocks or computes for long (skills, the
        # teleoperation steps) runs in threads of its own; see main() for why.
        self.create_subscription(JointState, "/joint_states", self._on_joints, 20)
        self.create_subscription(String, "/skill/request", self._on_request, 50)
        self.create_subscription(Bool, "/teleop/enable", self._on_teleop_enable, 5)
        self.create_subscription(Point, "/teleop/target", self._on_teleop_target, 5)
        self.create_subscription(Float32, "/teleop/gripper", self._on_teleop_gripper, 5)

        self.move_client = ActionClient(self, MoveGroup, "/move_action")
        self.gripper_client = ActionClient(
            self, FollowJointTrajectory, "/gripper_controller/follow_joint_trajectory")
        self.scene_client = self.create_client(ApplyPlanningScene, "/apply_planning_scene")

        self.create_timer(0.2, self._publish_state)
        self.create_timer(0.05, self._follow_held)
        self._last_scene = 0.0

        threading.Thread(target=self._worker, daemon=True).start()
        threading.Thread(target=self._teleop_loop, daemon=True).start()
        self.get_logger().info("Skill server started")

    # ------------------------------------------------------------- utilities

    def _tool(self):
        """Tool pose from the latest joint states: (rotation 3x3, position)."""
        q = self._arm_q()
        if q is None:
            return None
        pose = self.chain.fk(q)
        return pose[:3, :3], pose[:3, 3]

    def _arm_q(self):
        try:
            return np.array([self.joints[n] for n in self.arm_joints])
        except KeyError:
            return None

    def _wait(self, future, timeout: float, what: str, stoppable: bool = True):
        """Block the worker thread until a future completes (the executor runs it elsewhere).
        A stop request interrupts the wait, unless `stoppable` is False."""
        done = threading.Event()
        future.add_done_callback(lambda _f: done.set())
        deadline = time.monotonic() + timeout
        while not done.wait(0.05):
            if stoppable and self.stop_flag.is_set():
                raise Stopped()
            if time.monotonic() > deadline:
                raise SkillError(f"{what} did not answer")
        return future.result()

    def _status(self, request: dict, state: str, message: str = "") -> None:
        msg = {"id": request.get("id", ""), "skill": request.get("skill", ""), "state": state,
               "message": message, "description": describe(request)}
        if state != "running":
            self._publish_state()           # whoever reads the result also gets the final pose
        self.status_pub.publish(String(data=json.dumps(msg)))
        line = f"[{state}] {msg['description']}{': ' + message if message else ''}"
        if state == "failed":
            self.get_logger().warning(line)
        else:
            self.get_logger().info(line)

    def _publish_scene(self) -> None:
        with self.lock:
            data = json.dumps({"objects": self.world.snapshot(), "held": self.world.held})
        self.scene_pub.publish(String(data=data))
        self._last_scene = time.monotonic()

    def _publish_state(self) -> None:
        tool = self._tool()
        jaws = self._grasp_centre()
        state = {
            "busy": self.busy, "queue": self.requests.qsize(), "holding": self.world.held,
            "teleop": self.teleop, "ready": self._ready(),
            "current": describe(self.current) if self.current else "",
            "tool": [round(float(v), 4) for v in tool[1]] if tool else None,
            "jaws": [round(float(v), 4) for v in jaws] if jaws is not None else None,
            "gripper": round(self.joints.get(GRIPPER_JOINT, 0.0), 3),
            "hand": [round(v, 3) for v in self.hand] if self.hand and self.teleop else None,
        }
        self.state_pub.publish(String(data=json.dumps(state)))
        if time.monotonic() - self._last_scene > 2.0:
            self._publish_scene()       # for browsers that connected late

    def _ready(self) -> bool:
        return (self._arm_q() is not None and self.move_client.server_is_ready()
                and self.scene_client.service_is_ready())

    # -------------------------------------------------------- planning scene

    def _apply(self, scene: PlanningScene) -> None:
        scene.is_diff = True
        scene.robot_state.is_diff = True
        request = ApplyPlanningScene.Request(scene=scene)
        future = self.scene_client.call_async(request)
        if threading.current_thread() is threading.main_thread():
            return
        done = threading.Event()
        future.add_done_callback(lambda _f: done.set())
        done.wait(3.0)

    def _collision_object(self, obj, operation=CollisionObject.ADD) -> CollisionObject:
        co = CollisionObject()
        co.header.frame_id = BASE_FRAME
        co.id = obj.name
        co.operation = operation
        if operation == CollisionObject.REMOVE:
            return co
        prim = SolidPrimitive()
        sx, sy, sz = (max(0.01, s - SHRINK) for s in obj.size)
        if obj.shape == "sphere":
            prim.type, prim.dimensions = SolidPrimitive.SPHERE, [0.5 * min(sx, sy, sz)]
        elif obj.shape == "cylinder":
            prim.type, prim.dimensions = SolidPrimitive.CYLINDER, [sz, 0.5 * min(sx, sy)]
        else:
            prim.type, prim.dimensions = SolidPrimitive.BOX, [sx, sy, sz]
        pose = Pose()
        pose.position.x, pose.position.y, pose.position.z = float(obj.x), float(obj.y), float(obj.z)
        pose.orientation.w = 1.0
        co.primitives, co.primitive_poses = [prim], [pose]
        return co

    def _scene_add(self, obj) -> None:
        scene = PlanningScene()
        scene.world.collision_objects.append(self._collision_object(obj))
        self._apply(scene)

    def _scene_remove(self, obj) -> None:
        scene = PlanningScene()
        scene.world.collision_objects.append(self._collision_object(obj, CollisionObject.REMOVE))
        self._apply(scene)

    def _scene_attach(self, obj) -> None:
        """Tell MoveIt the object now moves with the gripper (so it plans around the pair)."""
        scene = PlanningScene()
        scene.world.collision_objects.append(self._collision_object(obj))
        self._apply(scene)
        scene = PlanningScene()
        attached = AttachedCollisionObject()
        attached.link_name = "gripper_link"
        attached.object.id = obj.name
        attached.object.header.frame_id = BASE_FRAME
        attached.object.operation = CollisionObject.ADD
        attached.touch_links = GRIPPER_TOUCH_LINKS
        scene.robot_state.attached_collision_objects.append(attached)
        self._apply(scene)

    def _scene_detach(self, obj, keep: bool = True) -> None:
        scene = PlanningScene()
        attached = AttachedCollisionObject()
        attached.link_name = "gripper_link"
        attached.object.id = obj.name
        attached.object.operation = CollisionObject.REMOVE
        scene.robot_state.attached_collision_objects.append(attached)
        self._apply(scene)
        # MoveIt drops the object back into the world where the gripper was; put it where it
        # actually came to rest, or take it out of the way.
        if keep:
            self._scene_add(obj)
        else:
            self._scene_remove(obj)

    def _scene_table(self) -> None:
        co = CollisionObject()
        co.header.frame_id = BASE_FRAME
        co.id = "table"
        prim = SolidPrimitive(type=SolidPrimitive.BOX, dimensions=[1.2, 1.2, 0.04])
        pose = Pose()
        pose.position.x, pose.position.z = 0.2, -0.004 - 0.02
        pose.orientation.w = 1.0
        co.primitives, co.primitive_poses, co.operation = [prim], [pose], CollisionObject.ADD
        scene = PlanningScene()
        scene.world.collision_objects.append(co)
        self._apply(scene)

    # ------------------------------------------------------------ arm motion

    def _move_joints(self, q, what: str = "move", speed: float = 1.0) -> None:
        """Plan and execute a collision-aware motion of the arm to joint angles `q`."""
        q = [float(v) for v in q]
        now = self._arm_q()
        if now is not None and np.abs(now - np.array(q)).max() < 0.004:
            return
        last_error = "no path found"
        for pipeline, planner in PIPELINES:
            goal = MoveGroup.Goal()
            request = goal.request
            request.group_name = ARM_GROUP
            request.pipeline_id = pipeline
            request.planner_id = planner
            request.num_planning_attempts = 1 if pipeline.startswith("pilz") else 4
            request.allowed_planning_time = 2.0
            request.max_velocity_scaling_factor = float(speed)
            request.max_acceleration_scaling_factor = float(speed)
            request.start_state.is_diff = True
            request.workspace_parameters.header.frame_id = BASE_FRAME
            low, high = request.workspace_parameters.min_corner, request.workspace_parameters.max_corner
            low.x, low.y, low.z, high.x, high.y, high.z = -1.0, -1.0, -0.5, 1.0, 1.0, 1.0
            constraints = Constraints()
            for name, value in zip(self.arm_joints, q):
                constraints.joint_constraints.append(JointConstraint(
                    joint_name=name, position=value, tolerance_above=0.002, tolerance_below=0.002,
                    weight=1.0))
            request.goal_constraints = [constraints]
            goal.planning_options.plan_only = False
            goal.planning_options.planning_scene_diff.is_diff = True
            goal.planning_options.planning_scene_diff.robot_state.is_diff = True

            # Not stoppable: a goal must never be left running without our knowing its handle.
            handle = self._wait(self.move_client.send_goal_async(goal), 10.0, "MoveIt", stoppable=False)
            if not handle.accepted:
                raise SkillError("MoveIt rejected the motion")
            self.goal_handle = handle
            result_future = handle.get_result_async()
            try:
                if self.stop_flag.is_set():         # the stop came while the goal was being sent
                    raise Stopped()
                result = self._wait(result_future, 40.0, "MoveIt").result
            except (Stopped, SkillError):
                self._cancel_and_settle(handle, result_future)
                raise
            finally:
                self.goal_handle = None
            code = result.error_code.val
            if code == MoveItErrorCodes.SUCCESS:
                self._wait_until_at(q)
                return
            if code == MoveItErrorCodes.PREEMPTED or self.stop_flag.is_set():
                raise Stopped()
            last_error = ERROR_TEXT.get(code, f"MoveIt error {code}")
            self.get_logger().info(f"{pipeline}: {last_error}")
        raise SkillError(f"cannot {what}: {last_error}")

    def _wait_until_at(self, q, timeout: float = 0.5, tolerance: float = 0.02) -> None:
        """Wait until the joint states this node has received show the arm at `q`.

        MoveIt reports success as soon as the controller is done, but this node's /joint_states
        can be a few messages behind when its executor is busy. Without this wait, the tool
        position and the held object were sometimes published from before the end of the motion.
        """
        target = np.array(q)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            now = self._arm_q()
            if now is not None and np.abs(now - target).max() < tolerance:
                return
            time.sleep(0.02)

    def _cancel_and_settle(self, handle, result_future) -> None:
        """Cancel a MoveIt goal and wait until MoveIt has really finished it.

        MoveIt must be done with a cancelled goal before it receives the next one. move_group
        (2.12) keeps a single "preempt requested" flag: a goal that arrives while the previous
        one is still being cancelled is cancelled as well, from a state that does not allow it,
        and move_group aborts ("invalid transition from state EXECUTING with event CANCELED").
        A stop followed at once by another command, such as Stop and then Home, did exactly that.
        """
        handle.cancel_goal_async()
        try:
            self._wait(result_future, 5.0, "MoveIt", stoppable=False)
        except SkillError:
            self.get_logger().warn("MoveIt did not confirm the end of the cancelled motion")

    def _solve(self, point, pitches=None, seed=None):
        """Inverse kinematics for a tool position; raises SkillError when out of reach."""
        kwargs = {"seed": seed if seed is not None else self._arm_q()}
        if pitches is not None:
            kwargs["pitches"] = pitches
            kwargs["position_only_fallback"] = False
        result = self.chain.solve(point, **kwargs)
        if result is None:
            raise SkillError(
                f"cannot reach x={point[0]:.2f} y={point[1]:.2f} z={point[2]:.2f}")
        return result

    def _solve_grasp(self, centre, width: float, pitches=None):
        """IK that puts the middle of the open jaws (not the fingertip) on `centre`.

        The fixed jaw sits at the tool frame; the moving jaw opens along -x of that frame.
        """
        target = np.array(centre, dtype=float)
        result = self._solve(target, pitches)
        for _ in range(3):
            rotation = self.chain.fk(result.joints)[:3, :3]
            shifted = target + rotation @ np.array([0.5 * width + 0.003, 0.0, 0.0])
            keep = (result.pitch,) if result.pitch is not None else pitches
            result = self._solve(shifted, pitches=keep, seed=result.joints)
        return result

    def _approach(self, centre, width: float, prefer: float = math.pi / 2):
        """Joint angles for grasping at `centre` and for a point straight above it.

        The short arm cannot point straight down everywhere. The gripper pitch closest to
        `prefer` that works for BOTH poses is used, so the object stays level while it is
        lifted; if no single pitch works, the pose above may use a neighbouring pitch.
        """
        order = sorted(PITCHES, key=lambda p: abs(p - prefer))
        up = lambda lift: (centre[0], centre[1], centre[2] + lift)  # noqa: E731
        for pitch in order:
            try:
                down = self._solve_grasp(centre, width, (pitch,))
            except SkillError:
                continue
            for lift in (APPROACH, 0.05):
                try:
                    return down, self._solve_grasp(up(lift), width, (pitch,))
                except SkillError:
                    continue
        down = self._solve_grasp(centre, width, order)
        near = sorted(PITCHES, key=lambda p: abs(p - (down.pitch if down.pitch is not None else prefer)))
        for lift in (APPROACH, 0.05, 0.035, 0.02):
            try:
                return down, self._solve_grasp(up(lift), width, near)
            except SkillError:
                continue
        raise SkillError(f"cannot get above x={centre[0]:.2f} y={centre[1]:.2f}")

    def _current_pitch(self):
        tool = self._tool()
        if tool is None:
            return None
        direction = tool[0] @ np.array([0.0, 0.0, 1.0])
        return float(math.asin(max(-1.0, min(1.0, -direction[2]))))

    # --------------------------------------------------------------- gripper

    def _move_gripper(self, angle: float, duration: float = 0.5) -> None:
        current = self.joints.get(GRIPPER_JOINT)
        if current is not None and abs(current - angle) < 0.01:
            return
        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = [GRIPPER_JOINT]
        point = JointTrajectoryPoint(positions=[float(angle)])
        point.time_from_start.sec = int(duration)
        point.time_from_start.nanosec = int((duration % 1.0) * 1e9)
        goal.trajectory.points = [point]
        if not self.gripper_client.wait_for_server(timeout_sec=5.0):
            raise SkillError("the gripper controller is not running")
        handle = self._wait(self.gripper_client.send_goal_async(goal), 5.0, "the gripper controller")
        if not handle.accepted:
            raise SkillError("the gripper controller rejected the command")
        self._wait(handle.get_result_async(), 10.0, "the gripper controller")

    def _grasp_centre(self):
        """Middle of the jaws, about 1 cm behind the fingertips."""
        tool = self._tool()
        if tool is None:
            return None
        opening = max(0.0, 0.0162 + 0.074 * self.joints.get(GRIPPER_JOINT, 0.0))
        return tool[1] + tool[0] @ np.array([-0.5 * opening, 0.0, 0.0])

    def _attach(self, obj) -> None:
        rotation, position = self._tool()
        with self.lock:
            self.grip_height = float(position[2] - (obj.z - 0.5 * obj.size[2]))
            self.grip_width = obj.width
            self.world.attach(obj.name, rotation.tolist(), position.tolist())
        self._scene_attach(obj)
        self._publish_scene()

    def _detach(self, at=None) -> None:
        with self.lock:
            obj = self.world.detach()
            if obj is None:
                return
            if at is not None:
                obj.x, obj.y = at
                base, _ = self.world.support(obj.x, obj.y, ignore=obj.name)
                obj.z = base + 0.5 * obj.size[2]
        self._scene_detach(obj)
        self._publish_scene()

    # ---------------------------------------------------------------- skills

    def _skill_spawn(self, request: dict) -> str:
        description = request["object"]
        words = description.split()
        coloured = len(words) > 1 and words[0] in COLORS
        kind = canonical_kind(" ".join(words[1:]) if coloured else description)
        spec = CATALOGUE.get(kind)
        # An object scanned with the webcam keeps the size it was given when it was scanned.
        scanned = None if coloured else models3d.scanned_size(kind, self.models_dir)
        radius = 0.5 * max((scanned or (spec and spec["size"]) or (0.05, 0.05))[:2])
        with self.lock:
            if len(self.world.objects) >= 16:
                raise SkillError("the table is full; remove something first")
            try:
                x, y, on = self.world.resolve_place(request.get("at"), radius, hand=self.hand)
            except ValueError as e:
                raise SkillError(str(e)) from None
        # "red cube": the plain shape in that colour. "apple": a detailed model if there is one.
        model = "" if coloured else models3d.find_model(kind, self.models_dir)
        with self.lock:
            obj = self.world.add(description, x, y, on=on, model=model, size=scanned)
        self._scene_add(obj)
        self._publish_scene()
        return f"created {obj.name}"

    def _skill_pick(self, request: dict) -> str:
        with self.lock:
            obj = self.world.find(request["object"])
            held = self.world.held
        if obj is None:
            raise SkillError(f"there is no {request['object']} on the table")
        if held == obj.name:
            return f"already holding the {obj.name}"
        if held:
            raise SkillError(f"the gripper already holds the {held}")
        if obj.width > MAX_GRASP_WIDTH:
            raise SkillError(f"the {obj.name} is too wide for the gripper")
        with self.lock:
            self.world.last = obj.name
            on_top = self.world.resting_on(obj.name)
        if on_top:
            raise SkillError(f"the {on_top[0]} is on top of the {obj.name}; move it first")

        grasp, above = self._approach(obj.grasp_point(), obj.width)

        self._move_gripper(gripper_angle(obj.width + 0.03))
        self._move_joints(above.joints, f"reach the {obj.name}")
        self._scene_remove(obj)                 # the jaws are allowed to surround it
        try:
            self._move_joints(grasp.joints, f"reach the {obj.name}", speed=0.6)
            self._move_gripper(gripper_angle(obj.width))
        except Exception:
            self._scene_add(obj)
            raise
        self._attach(obj)
        self._move_joints(above.joints, f"lift the {obj.name}", speed=0.8)
        return f"holding the {obj.name}"

    def _skill_place(self, request: dict) -> str:
        with self.lock:
            name = self.world.held
            obj = self.world.objects.get(name) if name else None
        if obj is None:
            raise SkillError("the gripper is empty")
        tool = self._tool()
        try:
            with self.lock:
                x, y, on = self.world.resolve_place(
                    request.get("at"), obj.radius, hand=self.hand, ignore=obj.name,
                    default=(obj.x, obj.y))
                base, _ = self.world.support(x, y, ignore=obj.name)
        except ValueError as e:
            raise SkillError(str(e)) from None
        if on == obj.name:
            raise SkillError(f"cannot put the {obj.name} on itself")
        # Same height above the object's bottom as when it was grasped.
        centre_height = self.grip_height - (tool[1][2] - self._grasp_centre()[2])
        centre = (x, y, base + centre_height + 0.003)
        pitch = self._current_pitch()
        down, above = self._approach(centre, self.grip_width,
                                     prefer=pitch if pitch is not None else math.pi / 2)
        self._move_joints(above.joints, "carry the object there")
        self._move_joints(down.joints, "put the object down", speed=0.6)
        self._move_gripper(gripper_angle(obj.width + 0.03))
        self._detach(at=(x, y))
        self._scene_remove(obj)                 # so the open jaws can leave without a "collision"
        try:
            self._move_joints(above.joints, "move away", speed=0.8)
        finally:
            self._scene_add(obj)
        where = f"on the {on}" if on else "on the table"
        return f"put the {obj.name} {where}"

    def _skill_move_to(self, request: dict) -> str:
        at = request["at"]
        with self.lock:
            held = self.world.objects.get(self.world.held) if self.world.held else None
            try:
                x, y, on = self.world.resolve_place(at, 0.0, hand=self.hand,
                                                    ignore=held.name if held else None)
            except ValueError as e:
                raise SkillError(str(e)) from None
            if "x" in at:
                x, y = float(at["x"]), float(at["y"])
            top = self.world.objects[on].top if on else self.world.support(x, y)[0]
        if "z" in at:
            z = float(at["z"])
        else:
            z = top + float(request.get("height", HOVER if not on else 0.08))
        if held:
            z = max(z, top + self.grip_height + 0.01)
        result = self._solve((x, y, max(0.012, z)))
        self._move_joints(result.joints, "move there")
        return "moved"

    def _skill_move_by(self, request: dict) -> str:
        tool = self._tool()
        target = tool[1] + np.array([request["dx"], request["dy"], request["dz"]])
        floor = 0.012 + (self.grip_height if self.world.held else 0.0)
        target[2] = max(floor, target[2])
        pitch = self._current_pitch() or math.pi / 2
        order = sorted(PITCHES, key=lambda p: abs(p - pitch))
        result = self.chain.solve(target, seed=self._arm_q(), pitches=order)
        if result is None:
            raise SkillError("cannot move further that way")
        self._move_joints(result.joints, "move there")
        return "moved"

    def _skill_gripper(self, request: dict) -> str:
        if request["state"] == "open":
            self._move_gripper(GRIPPER_OPEN)
            if self.world.held:
                name = self.world.held
                self._detach()
                return f"released the {name}"
            return "gripper open"
        centre = self._grasp_centre()
        with self.lock:
            obj = None if self.world.held else self.world.nearest(centre.tolist(), 0.035)
        if obj is not None and obj.width <= MAX_GRASP_WIDTH:
            self._scene_remove(obj)
            self._move_gripper(gripper_angle(obj.width))
            self._attach(obj)
            return f"holding the {obj.name}"
        self._move_gripper(gripper_angle(self.grip_width) if self.world.held else GRIPPER_CLOSED)
        return "gripper closed"

    def _skill_home(self, _request: dict) -> str:
        self._move_joints(HOME, "go home")
        return "at home"

    def _skill_remove(self, request: dict) -> str:
        with self.lock:
            obj = self.world.find(request["object"])
            if obj is None:
                raise SkillError(f"there is no {request['object']} on the table")
            was_held = obj.held
            self.world.remove(obj.name)
        if was_held:
            self._scene_detach(obj, keep=False)
        else:
            self._scene_remove(obj)
        self._publish_scene()
        return f"removed the {obj.name}"

    def _skill_reset(self, _request: dict) -> str:
        with self.lock:
            objects = list(self.world.objects.values())
            held = self.world.held
            self.world.clear()
        for obj in objects:
            if obj.name == held:
                self._scene_detach(obj, keep=False)
            else:
                self._scene_remove(obj)
        self._publish_scene()
        self._move_gripper(GRIPPER_OPEN)
        self._move_joints(HOME, "go home")
        return "table cleared"

    # ---------------------------------------------------------------- worker

    def _on_request(self, msg: String) -> None:
        try:
            raw = json.loads(msg.data)
            request = validate(raw)
        except (json.JSONDecodeError, ValueError) as e:
            bad = raw if isinstance(locals().get("raw"), dict) else {}
            self._status({"id": bad.get("id", ""), "skill": str(bad.get("skill", "?"))}, "failed",
                         f"bad request: {e}")
            return
        if request["skill"] == "stop":
            self._stop()
            self._status(request, "succeeded", "stopped")
            return
        self.requests.put(request)

    def _stop(self) -> None:
        """Cancel the motion in progress and forget everything that is queued."""
        dropped = []
        while True:
            try:
                dropped.append(self.requests.get_nowait())
            except queue.Empty:
                break
        for request in dropped:
            self._status(request, "stopped", "cancelled")
        if self.busy:
            self.stop_flag.set()
            handle = self.goal_handle
            if handle is not None:
                handle.cancel_goal_async()

    def _worker(self) -> None:
        # Wait for the robot, then put the table into MoveIt's world.
        while rclpy.ok() and not self._ready():
            time.sleep(0.2)
        self._scene_table()
        self.get_logger().info("Robot ready: MoveIt and the controllers are up")
        handlers = {
            "spawn": self._skill_spawn, "pick": self._skill_pick, "place": self._skill_place,
            "move_to": self._skill_move_to, "move_by": self._skill_move_by,
            "gripper": self._skill_gripper, "home": self._skill_home,
            "remove": self._skill_remove, "reset": self._skill_reset,
        }
        while rclpy.ok():
            try:
                request = self.requests.get(timeout=0.2)
            except queue.Empty:
                continue
            self.stop_flag.clear()
            self.busy, self.current = True, request
            self._status(request, "running")
            try:
                outcome = ("succeeded", handlers[request["skill"]](request))
            except Stopped:
                outcome = ("stopped", "stopped")
            except SkillError as e:
                outcome = ("failed", str(e))
            except Exception as e:  # noqa: BLE001  a bug in one skill must not kill the robot
                self.get_logger().error(f"Skill crashed: {e!r}")
                outcome = ("failed", f"internal error: {e}")
            finally:
                self.busy, self.current = False, None
                self._teleop_restart = True     # teleoperation resumes from where the arm is now
            # Not busy any more before the result goes out: the state published with it says so.
            self._status(request, *outcome)

    # ------------------------------------------------------------- callbacks

    def _on_joints(self, msg: JointState) -> None:
        for name, position in zip(msg.name, msg.position):
            self.joints[name] = position

    def _follow_held(self) -> None:
        """Make the held object move with the gripper and tell the browser."""
        if not self.world.held:
            return
        tool = self._tool()
        if tool is None:
            return
        try:
            with self.lock:
                self.world.follow(tool[0].tolist(), tool[1].tolist())
            self._publish_scene()
        except Exception as e:  # noqa: BLE001
            self.get_logger().error(f"Could not update the held object: {e!r}", throttle_duration_sec=2.0)

    # ---------------------------------------------------------- teleoperation

    def _on_teleop_enable(self, msg: Bool) -> None:
        if msg.data != self.teleop:
            self.get_logger().info(f"Hand teleoperation {'on' if msg.data else 'off'}")
        self.teleop = bool(msg.data)
        self.teleop_target = None
        self.teleop_gripper = None
        self._teleop_restart = True         # picked up by the next tick (another thread)

    def _on_teleop_target(self, msg: Point) -> None:
        self.teleop_target = np.array([msg.x, msg.y, msg.z])
        self.teleop_target_time = time.monotonic()
        self.hand = (float(msg.x), float(msg.y), float(msg.z))

    def _on_teleop_gripper(self, msg: Float32) -> None:
        self.teleop_gripper = max(0.0, min(1.0, float(msg.data)))

    def _teleop_loop(self) -> None:
        """Teleoperation steps, TELEOP_RATE times a second, in a thread of their own.

        Not an executor timer: a step solves inverse kinematics in Python (15-30 ms), and
        grasping waits for the planning scene service, whose answer the executor must deliver.
        """
        period = 1.0 / TELEOP_RATE
        next_tick = time.monotonic()
        while rclpy.ok():
            if self.teleop and not self.busy and self.teleop_target is not None:
                try:
                    self._teleop_step()
                except Exception as e:  # noqa: BLE001  a bad tick must never take the robot down
                    self.get_logger().error(f"Teleoperation step failed: {e!r}", throttle_duration_sec=2.0)
            next_tick += period
            delay = next_tick - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_tick = time.monotonic()    # running late: do not try to catch up

    def _teleop_step(self) -> None:
        if time.monotonic() - self.teleop_target_time > 0.5:
            return                              # the hand left the camera: hold still
        now = self._arm_q()
        target_now = self.teleop_target
        if now is None or target_now is None:
            return
        if self._teleop_restart or self.teleop_q is None:
            self._teleop_restart = False
            self.teleop_q = now
            self.teleop_tip = self.chain.position(now)

        # The hand steers the middle of the jaws, not the fingertip of the fixed jaw.
        opening = max(0.0, 0.0162 + 0.074 * self.joints.get(GRIPPER_JOINT, 0.0))
        rotation = self.chain.fk(self.teleop_q)[:3, :3]
        target = target_now + rotation @ np.array([0.5 * opening, 0.0, 0.0])
        # Stay over the table and inside the arm's reach.
        floor = 0.015 + (self.grip_height if self.world.held else 0.0)
        target[0] = max(0.08, min(0.38, target[0]))
        target[1] = max(-0.28, min(0.28, target[1]))
        target[2] = max(floor, min(0.32, target[2]))
        step = target - self.teleop_tip
        distance = float(np.linalg.norm(step))
        if distance > TELEOP_MAX_STEP:
            target = self.teleop_tip + step * (TELEOP_MAX_STEP / distance)

        if distance > 0.002:
            result = self.chain.solve(target, seed=self.teleop_q, iterations=40, tolerance=0.004)
            if not self.teleop or self.busy:
                return                          # switched off, or a skill started, meanwhile
            if result is not None:
                change = result.joints - self.teleop_q
                biggest = float(np.abs(change).max())
                if biggest > 0.35:              # never jump between very different postures
                    change *= 0.35 / biggest
                self.teleop_q = self.teleop_q + change
                self.teleop_tip = self.chain.position(self.teleop_q)
                trajectory = JointTrajectory(joint_names=list(self.arm_joints))
                point = JointTrajectoryPoint(positions=[float(v) for v in self.teleop_q])
                point.time_from_start.nanosec = int(1.5e9 / TELEOP_RATE)
                trajectory.points = [point]
                self.arm_pub.publish(trajectory)

        if self.teleop_gripper is not None:
            self._teleop_gripper_step()

    def _teleop_gripper_step(self) -> None:
        """Pinch to grasp: closing the fingers around an object picks it up."""
        opening = 0.085 * self.teleop_gripper           # jaw opening in metres
        with self.lock:
            held = self.world.objects.get(self.world.held) if self.world.held else None
        if held is None and opening < 0.06:
            centre = self._grasp_centre()
            with self.lock:
                obj = self.world.nearest(centre.tolist(), 0.03) if centre is not None else None
            if obj is not None and obj.width <= MAX_GRASP_WIDTH and opening <= obj.width + 0.004:
                self._attach(obj)
                held = obj
        elif held is not None and opening > held.width + 0.02:
            self._detach()
            held = None
        if held is not None:
            opening = max(opening, held.width)
        angle = gripper_angle(opening)
        if abs(angle - self.joints.get(GRIPPER_JOINT, 0.0)) > 0.02:
            trajectory = JointTrajectory(joint_names=[GRIPPER_JOINT])
            point = JointTrajectoryPoint(positions=[float(angle)])
            point.time_from_start.nanosec = int(1.5e8)
            trajectory.points = [point]
            self.gripper_pub.publish(trajectory)


def main(args=None):
    rclpy.init(args=args)
    node = SkillServer()
    # Single-threaded on purpose. With the 100 Hz /joint_states, rclpy's MultiThreadedExecutor
    # (Jazzy) kept a core busy and the GIL taken almost all the time: an inverse-kinematics step
    # that takes 15 ms on its own then took up to 1.8 s, and hand teleoperation stalled.
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
