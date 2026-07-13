import math
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from visualization_msgs.msg import Marker, MarkerArray
from geometry_msgs.msg import Point
from std_msgs.msg import ColorRGBA


def rotation_z(theta):
    ct, st = math.cos(theta), math.sin(theta)
    return ((ct, -st, 0), (st, ct, 0), (0, 0, 1))


def rotation_y(theta):
    ct, st = math.cos(theta), math.sin(theta)
    return ((ct, 0, st), (0, 1, 0), (-st, 0, ct))


def mat_vec_mul(mat, vec):
    x, y, z = vec
    return (
        mat[0][0] * x + mat[0][1] * y + mat[0][2] * z,
        mat[1][0] * x + mat[1][1] * y + mat[1][2] * z,
        mat[2][0] * x + mat[2][1] * y + mat[2][2] * z,
    )


def vec_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def vec_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vec_scale(v, s):
    return (v[0] * s, v[1] * s, v[2] * s)


def vec_norm(v):
    return math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)


def vec_normalize(v):
    n = vec_norm(v)
    if n < 1e-9:
        return (0.0, 0.0, 1.0)
    return (v[0] / n, v[1] / n, v[2] / n)


def quaternion_from_direction(dx, dy, dz):
    norm = math.sqrt(dx * dx + dy * dy + dz * dz)
    if norm < 1e-9:
        return (0.0, 0.0, 0.0, 1.0)
    dx, dy, dz = dx / norm, dy / norm, dz / norm
    dot = dz
    if abs(dot - 1.0) < 1e-9:
        return (0.0, 0.0, 0.0, 1.0)
    if abs(dot + 1.0) < 1e-9:
        return (0.0, 1.0, 0.0, 0.0)
    angle = math.acos(dot)
    axis_x = -dy
    axis_y = dx
    axis_len = math.sqrt(axis_x * axis_x + axis_y * axis_y)
    if axis_len < 1e-9:
        return (0.0, 0.0, 0.0, 1.0)
    axis_x /= axis_len
    axis_y /= axis_len
    s = math.sin(angle / 2.0)
    return (axis_x * s, axis_y * s, 0.0, math.cos(angle / 2.0))


def make_marker(link_name, pos, quat, scale, color, stamp=None, frame_id="base_link"):
    if stamp is None:
        stamp = rclpy.clock.Clock().now().to_msg()
    m = Marker()
    m.header.frame_id = frame_id
    m.header.stamp = stamp
    m.ns = "arm"
    m.id = hash(link_name) & 0x7FFFFFFF
    m.type = Marker.CUBE
    m.action = Marker.ADD
    m.pose.position.x = float(pos[0])
    m.pose.position.y = float(pos[1])
    m.pose.position.z = float(pos[2])
    m.pose.orientation.w = float(quat[3])
    m.pose.orientation.x = float(quat[0])
    m.pose.orientation.y = float(quat[1])
    m.pose.orientation.z = float(quat[2])
    m.scale.x = float(scale[0])
    m.scale.y = float(scale[1])
    m.scale.z = float(scale[2])
    m.color = color
    m.lifetime.sec = 0
    return m


def make_cylinder_marker(ns, link_name, start_pos, end_pos, radius, color, stamp=None):
    if stamp is None:
        stamp = rclpy.clock.Clock().now().to_msg()
    mid = vec_scale(vec_add(start_pos, end_pos), 0.5)
    direction = vec_sub(end_pos, start_pos)
    length = vec_norm(direction)
    if length < 1e-9:
        return None
    q = quaternion_from_direction(float(direction[0]), float(direction[1]), float(direction[2]))
    m = Marker()
    m.header.frame_id = "base_link"
    m.header.stamp = stamp
    m.ns = ns
    m.id = abs(hash(link_name)) & 0x7FFFFFFF
    m.type = Marker.CYLINDER
    m.action = Marker.ADD
    m.pose.position.x = float(mid[0])
    m.pose.position.y = float(mid[1])
    m.pose.position.z = float(mid[2])
    m.pose.orientation.x = float(q[0])
    m.pose.orientation.y = float(q[1])
    m.pose.orientation.z = float(q[2])
    m.pose.orientation.w = float(q[3])
    m.scale.x = float(radius * 2.0)
    m.scale.y = float(radius * 2.0)
    m.scale.z = float(length)
    m.color = color
    m.lifetime.sec = 0
    return m


def make_joint_sphere(joint_name, pos, radius, color, stamp=None):
    if stamp is None:
        stamp = rclpy.clock.Clock().now().to_msg()
    m = Marker()
    m.header.frame_id = "base_link"
    m.header.stamp = stamp
    m.ns = "arm_joints"
    m.id = abs(hash(joint_name)) & 0x7FFFFFFF
    m.type = Marker.SPHERE
    m.action = Marker.ADD
    m.pose.position.x = float(pos[0])
    m.pose.position.y = float(pos[1])
    m.pose.position.z = float(pos[2])
    m.pose.orientation.w = 1.0
    m.scale.x = float(radius * 2.0)
    m.scale.y = float(radius * 2.0)
    m.scale.z = float(radius * 2.0)
    m.color = color
    m.lifetime.sec = 0
    return m


class JointStateToMarkers(Node):
    LINK_COLORS = {
        "base": ColorRGBA(r=0.5, g=0.5, b=0.5, a=1.0),
        "shoulder": ColorRGBA(r=0.2, g=0.3, b=0.8, a=1.0),
        "upper_arm": ColorRGBA(r=0.8, g=0.2, b=0.2, a=1.0),
        "forearm": ColorRGBA(r=0.2, g=0.8, b=0.2, a=1.0),
        "gripper": ColorRGBA(r=0.8, g=0.8, b=0.2, a=1.0),
        "joint": ColorRGBA(r=1.0, g=1.0, b=1.0, a=0.8),
    }

    def __init__(self):
        super().__init__("joint_state_to_markers")
        self.sub = self.create_subscription(JointState, "/joint_states", self.on_joint_states, 10)
        self.pub = self.create_publisher(MarkerArray, "/visualization_marker_array", 10)
        self.get_logger().info("Joint State to Markers node started")

    def on_joint_states(self, msg):
        try:
            theta1 = msg.position[msg.name.index("base_joint")]
            theta2 = msg.position[msg.name.index("shoulder_joint")]
            theta3 = msg.position[msg.name.index("elbow_joint")]
            grip = msg.position[msg.name.index("gripper_joint")]
        except (ValueError, IndexError):
            self.get_logger().warn("Missing joint in JointState message")
            return

        markers = self._compute_markers(theta1, theta2, theta3, grip)
        self.pub.publish(markers)

    def _compute_markers(self, theta1, theta2, theta3, grip=0.0):
        markers = MarkerArray()
        now = self.get_clock().now().to_msg()

        R_z1 = rotation_z(theta1)
        R_y2 = rotation_y(theta2)
        R_y3 = rotation_y(theta3)

        r23 = rotation_y(theta2 + theta3)

        p_shoulder = (0.0, 0.0, 0.025)
        p_upper = (0.0, 0.0, 0.20)
        elbow_offset = mat_vec_mul(R_z1, mat_vec_mul(R_y2, (0.0, 0.0, 0.25)))
        p_elbow = vec_add(p_upper, elbow_offset)
        gripper_offset = mat_vec_mul(R_z1, mat_vec_mul(r23, (0.0, 0.0, 0.25)))
        p_gripper = vec_add(p_elbow, gripper_offset)

        base_color = self.LINK_COLORS["base"]
        shoulder_color = self.LINK_COLORS["shoulder"]
        upper_color = self.LINK_COLORS["upper_arm"]
        forearm_color = self.LINK_COLORS["forearm"]
        gripper_color = self.LINK_COLORS["gripper"]
        joint_color = self.LINK_COLORS["joint"]

        m = make_cylinder_marker("arm_links", "base", (0.0, 0.0, 0.0), p_shoulder, 0.075, base_color, stamp=now)
        if m:
            markers.markers.append(m)

        m = make_cylinder_marker("arm_links", "shoulder", p_shoulder, p_upper, 0.03, shoulder_color, stamp=now)
        if m:
            markers.markers.append(m)

        upper_rad = 0.025
        upper_visual_center = mat_vec_mul(R_z1, mat_vec_mul(R_y2, (0.0, 0.0, 0.125)))
        p_upper_center = vec_add(p_upper, upper_visual_center)
        upper_dir = mat_vec_mul(R_z1, mat_vec_mul(R_y2, (0.0, 0.0, 1.0)))
        upper_q = quaternion_from_direction(*upper_dir)
        m = make_marker("upper_arm_visual", p_upper_center, upper_q,
                        (0.05, 0.05, 0.25), upper_color, stamp=now)
        markers.markers.append(m)

        forearm_visual_center = mat_vec_mul(R_z1, mat_vec_mul(r23, (0.0, 0.0, 0.125)))
        p_forearm_center = vec_add(p_elbow, forearm_visual_center)
        forearm_dir = mat_vec_mul(R_z1, mat_vec_mul(r23, (0.0, 0.0, 1.0)))
        forearm_q = quaternion_from_direction(*forearm_dir)
        m = make_marker("forearm_visual", p_forearm_center, forearm_q,
                        (0.04, 0.04, 0.25), forearm_color, stamp=now)
        markers.markers.append(m)

        spread = 0.03 - grip * 0.4
        finger_dir = mat_vec_mul(R_z1, mat_vec_mul(r23, (0.0, 1.0, 0.0)))

        left_finger_pos = vec_add(p_gripper, vec_scale(finger_dir, spread))
        right_finger_pos = vec_add(p_gripper, vec_scale(finger_dir, -spread))
        finger_q = quaternion_from_direction(*mat_vec_mul(R_z1, mat_vec_mul(r23, (0.0, 0.0, 1.0))))

        m = make_marker("gripper_left", left_finger_pos, finger_q,
                        (0.01, 0.03, 0.04), gripper_color, stamp=now)
        markers.markers.append(m)
        m = make_marker("gripper_right", right_finger_pos, finger_q,
                        (0.01, 0.03, 0.04), gripper_color, stamp=now)
        markers.markers.append(m)

        for name, pos in [("base_joint", (0.0, 0.0, 0.0)),
                          ("shoulder_joint", p_shoulder),
                          ("upper_joint", p_upper),
                          ("elbow_joint", p_elbow),
                          ("gripper_joint", p_gripper)]:
            m = make_joint_sphere(name, pos, 0.01, joint_color, stamp=now)
            markers.markers.append(m)

        self.get_logger().debug(
            f"Published arm markers (θ1={math.degrees(theta1):.1f}°, "
            f"θ2={math.degrees(theta2):.1f}°, θ3={math.degrees(theta3):.1f}°)"
        )
        return markers


def main(args=None):
    rclpy.init(args=args)
    node = JointStateToMarkers()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
