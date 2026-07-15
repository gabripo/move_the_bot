import math
import rclpy
from rclpy.node import Node
from rclpy.callback_groups import ReentrantCallbackGroup
from geometry_msgs.msg import PoseStamped, Pose, Point
from sensor_msgs.msg import JointState
from std_msgs.msg import Header, String, ColorRGBA
from visualization_msgs.msg import Marker, MarkerArray
from moveit_msgs.srv import GetPositionIK, GetMotionPlan
from moveit_msgs.msg import (
    CollisionObject, PlanningScene, PlanningSceneWorld,
    MotionPlanRequest, Constraints, JointConstraint,
    PositionIKRequest, MoveItErrorCodes,
)
from shape_msgs.msg import SolidPrimitive


class MockMotionPlanningNode(Node):
    JOINT_NAMES = ["base_joint", "shoulder_joint", "elbow_joint", "gripper_joint"]

    def __init__(self):
        super().__init__("mock_motion_planning_node")

        self.cb_group = ReentrantCallbackGroup()

        self.joint_pub = self.create_publisher(JointState, "/joint_states", 10)
        self.scene_pub = self.create_publisher(PlanningScene, "/planning_scene", 10)
        self.traj_marker_pub = self.create_publisher(MarkerArray, "/visualization_marker_array", 10)

        self.goal_sub = self.create_subscription(
            PoseStamped, "/target_goal", self.goal_callback, 10
        )

        self.joint_sub = self.create_subscription(
            JointState, "/joint_states", self.joint_callback, 10,
            callback_group=self.cb_group,
        )

        self.reset_sub = self.create_subscription(
            String, "/reset_command", self.reset_callback, 10,
        )

        self.grasp_sub = self.create_subscription(
            String, "/grasp_command", self.grasp_callback, 10,
        )

        self.current_positions = [0.0, 0.0, 0.0, 0.0]
        self._planning = False

        self._trajectory = None
        self._trajectory_start = None
        self._trajectory_done = True

        self.timer = self.create_timer(0.05, self.publish_current_state)

        self._plan_client = self.create_client(
            GetMotionPlan, "/plan_kinematic_path", callback_group=self.cb_group
        )
        self._ik_client = self.create_client(
            GetPositionIK, "/compute_ik", callback_group=self.cb_group
        )

        self.add_collision_objects()

        self.publish_current_state()
        self.get_logger().info("Mock Motion Planning Node started")

    def joint_callback(self, msg):
        for name in self.JOINT_NAMES:
            if name in msg.name:
                idx = msg.name.index(name)
                if idx < len(msg.position):
                    self.current_positions[self.JOINT_NAMES.index(name)] = msg.position[idx]

    def add_collision_objects(self):
        scene = PlanningScene()
        scene.is_diff = True
        scene.robot_state.is_diff = True

        table = CollisionObject()
        table.id = "table"
        table.header.frame_id = "base_link"
        table.header.stamp = self.get_clock().now().to_msg()
        table.primitive_poses.append(Pose())
        table.primitive_poses[0].position.x = 0.0
        table.primitive_poses[0].position.y = 0.25
        table.primitive_poses[0].position.z = -0.025
        table.primitive_poses[0].orientation.w = 1.0
        table.primitives.append(SolidPrimitive())
        table.primitives[0].type = SolidPrimitive.BOX
        table.primitives[0].dimensions = [1.0, 0.5, 0.05]
        table.operation = CollisionObject.ADD

        scene.world = PlanningSceneWorld()
        scene.world.collision_objects.append(table)
        self.scene_pub.publish(scene)
        self.get_logger().info("Added table to planning scene")

    L0 = 0.20
    L1 = 0.25
    L2 = 0.25

    @staticmethod
    def _gripper_fk(theta1, theta2, theta3, d4):
        r = MockMotionPlanningNode.L1 * math.sin(theta2) \
            + MockMotionPlanningNode.L2 * math.sin(theta2 + theta3)
        x = r * math.cos(theta1)
        y = r * math.sin(theta1)
        z = MockMotionPlanningNode.L0 \
            + MockMotionPlanningNode.L1 * math.cos(theta2) \
            + MockMotionPlanningNode.L2 * math.cos(theta2 + theta3)
        return (x, y, z)

    def _clear_trajectory_markers(self, stamp):
        array = MarkerArray()
        for ns in ["trajectory_waypoints", "trajectory_path", "trajectory_goal"]:
            m = Marker()
            m.header.frame_id = "base_link"
            m.header.stamp = stamp
            m.ns = ns
            m.action = Marker.DELETEALL
            array.markers.append(m)
        self.traj_marker_pub.publish(array)

    def _publish_trajectory_markers(self, joint_trajectory):
        stamp = self.get_clock().now().to_msg()
        self._clear_trajectory_markers(stamp)

        points = joint_trajectory.points
        if not points:
            return

        joint_names = joint_trajectory.joint_names
        array = MarkerArray()

        def joint_val(name, point):
            if name in joint_names:
                return point.positions[joint_names.index(name)]
            return 0.0

        line = Marker()
        line.header.frame_id = "base_link"
        line.header.stamp = stamp
        line.ns = "trajectory_path"
        line.id = 0
        line.type = Marker.LINE_STRIP
        line.action = Marker.ADD
        line.scale.x = 0.008
        line.color = ColorRGBA(r=1.0, g=0.7, b=0.0, a=0.8)
        line.pose.orientation.w = 1.0

        n = len(points)
        for i, point in enumerate(points):
            t1 = joint_val("base_joint", point)
            t2 = joint_val("shoulder_joint", point)
            t3 = joint_val("elbow_joint", point)
            d4 = joint_val("gripper_joint", point)
            pos = self._gripper_fk(t1, t2, t3, d4)

            p = Point()
            p.x = pos[0]
            p.y = pos[1]
            p.z = pos[2]
            line.points.append(p)

            sphere = Marker()
            sphere.header.frame_id = "base_link"
            sphere.header.stamp = stamp
            sphere.ns = "trajectory_waypoints"
            sphere.id = i
            sphere.type = Marker.SPHERE
            sphere.action = Marker.ADD
            sphere.pose.position.x = pos[0]
            sphere.pose.position.y = pos[1]
            sphere.pose.position.z = pos[2]
            sphere.pose.orientation.w = 1.0
            sphere.scale.x = 0.025
            sphere.scale.y = 0.025
            sphere.scale.z = 0.025
            t = i / max(n - 1, 1)
            sphere.color = ColorRGBA(r=t, g=1.0 - t, b=0.0, a=0.9)
            sphere.lifetime.sec = 30
            array.markers.append(sphere)

        line.lifetime.sec = 30
        array.markers.append(line)

        goal = Marker()
        goal.header.frame_id = "base_link"
        goal.header.stamp = stamp
        goal.ns = "trajectory_goal"
        goal.id = 0
        goal.type = Marker.SPHERE
        goal.action = Marker.ADD
        gp = points[-1]
        gpos = self._gripper_fk(
            joint_val("base_joint", gp),
            joint_val("shoulder_joint", gp),
            joint_val("elbow_joint", gp),
            joint_val("gripper_joint", gp),
        )
        goal.pose.position.x = gpos[0]
        goal.pose.position.y = gpos[1]
        goal.pose.position.z = gpos[2]
        goal.pose.orientation.w = 1.0
        goal.scale.x = 0.05
        goal.scale.y = 0.05
        goal.scale.z = 0.05
        goal.color = ColorRGBA(r=1.0, g=0.2, b=0.1, a=0.9)
        goal.lifetime.sec = 30
        array.markers.append(goal)

        self.traj_marker_pub.publish(array)
        n_wp = len(points)
        self.get_logger().info(
            f"Published {n_wp} trajectory waypoint markers"
        )

    def reset_callback(self, msg: String):
        if msg.data != "reset":
            return
        self.get_logger().info("Resetting arm to home position")
        self.current_positions = [0.0, 0.0, 0.0, 0.0]
        self._planning = False
        self._trajectory = None
        self._trajectory_done = True

        stamp = self.get_clock().now().to_msg()
        self._clear_trajectory_markers(stamp)

        scene = PlanningScene()
        scene.is_diff = True
        scene.robot_state.is_diff = True

        remove = CollisionObject()
        remove.id = "table"
        remove.header.frame_id = "base_link"
        remove.header.stamp = stamp
        remove.operation = CollisionObject.REMOVE

        scene.world = PlanningSceneWorld()
        scene.world.collision_objects.append(remove)
        self.scene_pub.publish(scene)

        self.add_collision_objects()
        self.publish_current_state()

    def grasp_callback(self, msg: String):
        if msg.data == "grasp":
            self.current_positions[3] = 0.05
            self.get_logger().info("Gripper closed (grasp)")
            self.publish_current_state()
        elif msg.data == "release":
            self.current_positions[3] = 0.0
            self.get_logger().info("Gripper opened (release)")
            self.publish_current_state()

    def publish_current_state(self):
        if self._trajectory is not None and not self._trajectory_done:
            now = self.get_clock().now()
            elapsed = (now - self._trajectory_start).nanoseconds / 1e9
            points = self._trajectory.points
            last = points[-1]
            total_time = last.time_from_start.sec + last.time_from_start.nanosec / 1e9

            if elapsed >= total_time:
                traj_positions = list(last.positions)
                self._trajectory_done = True
                self.get_logger().info("Trajectory execution complete")
            else:
                for point in points:
                    t = point.time_from_start.sec + point.time_from_start.nanosec / 1e9
                    if t >= elapsed:
                        traj_positions = list(point.positions)
                        break

            for i, name in enumerate(self._trajectory.joint_names):
                if name in self.JOINT_NAMES:
                    idx = self.JOINT_NAMES.index(name)
                    self.current_positions[idx] = traj_positions[i]

        msg = JointState()
        msg.header = Header()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = self.JOINT_NAMES
        msg.position = self.current_positions
        self.joint_pub.publish(msg)

    def goal_callback(self, msg: PoseStamped):
        if self._planning:
            self.get_logger().info("Already planning, ignoring goal")
            return

        self._planning = True
        self.get_logger().info(
            f"Goal received: ({msg.pose.position.x:.3f}, "
            f"{msg.pose.position.y:.3f}, {msg.pose.position.z:.3f})"
        )

        if not self._ik_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error("/compute_ik service not available")
            self._planning = False
            return

        ik_request = PositionIKRequest()
        ik_request.group_name = "arm_with_gripper"
        ik_request.ik_link_name = "gripper_link"
        ik_request.pose_stamped = msg
        ik_request.avoid_collisions = False

        ik_request.robot_state.joint_state.name = self.JOINT_NAMES
        ik_request.robot_state.joint_state.position = self.current_positions

        ik_request.timeout.sec = 1

        request = GetPositionIK.Request()
        request.ik_request = ik_request

        future = self._ik_client.call_async(request)
        future.add_done_callback(self._ik_callback)

    def _ik_callback(self, future):
        ik_response = future.result()
        if ik_response.error_code.val != MoveItErrorCodes.SUCCESS:
            self.get_logger().error(
                f"IK failed (error={ik_response.error_code.val})"
            )
            self._planning = False
            return

        ik_joints = {}
        for name, pos in zip(
            ik_response.solution.joint_state.name,
            ik_response.solution.joint_state.position,
        ):
            ik_joints[name] = pos

        self.get_logger().info(f"IK solution found: {ik_joints}")

        joint_constraints = []
        for name in self.JOINT_NAMES:
            if name not in ik_joints:
                continue
            jc = JointConstraint()
            jc.joint_name = name
            jc.position = ik_joints[name]
            jc.tolerance_above = 0.01
            jc.tolerance_below = 0.01
            jc.weight = 1.0
            joint_constraints.append(jc)

        constraints = Constraints()
        constraints.joint_constraints = joint_constraints

        plan_request = MotionPlanRequest()
        plan_request.pipeline_id = "ompl"
        plan_request.group_name = "arm_with_gripper"
        plan_request.num_planning_attempts = 10
        plan_request.allowed_planning_time = 10.0
        plan_request.planner_id = "RRTConnect"
        plan_request.max_velocity_scaling_factor = 1.0
        plan_request.max_acceleration_scaling_factor = 1.0
        plan_request.goal_constraints.append(constraints)

        plan_request.start_state.is_diff = True
        plan_request.start_state.joint_state.name = self.JOINT_NAMES
        plan_request.start_state.joint_state.position = self.current_positions

        plan_service_request = GetMotionPlan.Request()
        plan_service_request.motion_plan_request = plan_request

        if not self._plan_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error("/plan_kinematic_path service not available")
            self._planning = False
            return

        future = self._plan_client.call_async(plan_service_request)
        future.add_done_callback(self._plan_callback)

    def _feedback_callback(self, feedback_msg):
        pass

    def _plan_callback(self, future):
        response = future.result()
        result = response.motion_plan_response
        if result.error_code.val != MoveItErrorCodes.SUCCESS:
            self.get_logger().error(
                f"Planning failed (error={result.error_code.val})"
            )
            self._planning = False
            return

        trajectory = result.trajectory
        n_points = len(trajectory.joint_trajectory.points)
        self.get_logger().info(
            f"Plan found: {n_points} waypoints ({result.planning_time:.2f}s)"
        )
        self._trajectory = trajectory.joint_trajectory
        self._trajectory_start = self.get_clock().now()
        self._trajectory_done = False
        self._planning = False

        self._publish_trajectory_markers(self._trajectory)


def main(args=None):
    rclpy.init(args=args)
    node = MockMotionPlanningNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
