import math
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Point
from sensor_msgs.msg import JointState
from std_msgs.msg import String, Header
from ros_nodes.kinematics import inverse_kinematics, L0, L1, L2


class MockKinematicsNode(Node):
    def __init__(self):
        super().__init__("mock_kinematics_node")
        self.sub = self.create_subscription(Point, "/target_goal", self.goal_callback, 10)
        self.sub_grasp = self.create_subscription(String, "/grasp_command", self.grasp_callback, 10)
        self.sub_reset = self.create_subscription(String, "/reset_command", self.reset_callback, 10)
        self.joint_pub = self.create_publisher(JointState, "/joint_states", 10)

        self.initial_angles = (0.0, 0.0, 0.0)
        self.current_angles = self.initial_angles
        self.is_grasping = False
        self.get_logger().info("Mock Kinematics Node started")

    def reset_callback(self, msg):
        if msg.data != "reset":
            return
        self.current_angles = self.initial_angles
        self.is_grasping = False
        self._publish_joint_state()
        self.get_logger().info("Reset to initial angles")

    def _publish_joint_state(self):
        joint_state = JointState()
        joint_state.header = Header()
        joint_state.header.stamp = self.get_clock().now().to_msg()
        joint_state.name = ["base_joint", "shoulder_joint", "elbow_joint", "gripper_joint"]
        joint_state.position = [
            self.current_angles[0],
            self.current_angles[1],
            self.current_angles[2],
            0.05 if self.is_grasping else 0.0,
        ]
        self.joint_pub.publish(joint_state)

    def grasp_callback(self, msg):
        self.is_grasping = msg.data == "grasp"
        self.get_logger().info(f"Gripper: {'closed' if self.is_grasping else 'open'}")

    def goal_callback(self, msg):
        x, y, z = msg.x, msg.y, msg.z
        ik_result = inverse_kinematics(x, y, z)
        if ik_result is None:
            self.get_logger().warn(f"Target ({x:.3f}, {y:.3f}, {z:.3f}) unreachable")
            return

        self.current_angles = ik_result
        self.get_logger().info(
            f"IK: θ1={math.degrees(ik_result[0]):.1f}° "
            f"θ2={math.degrees(ik_result[1]):.1f}° "
            f"θ3={math.degrees(ik_result[2]):.1f}°"
        )
        self._publish_joint_state()


def main(args=None):
    rclpy.init(args=args)
    node = MockKinematicsNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
