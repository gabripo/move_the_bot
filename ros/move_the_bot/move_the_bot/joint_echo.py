"""A stand-in for Isaac Sim's joint interface, for testing `hardware:=isaac` without Isaac Sim.

Isaac Sim's ROS 2 bridge listens for joint commands on one topic and publishes the simulated
joint states on another. This node does the same with a simple model: every joint moves
towards its commanded position with a little lag.

  ros2 run move_the_bot joint_echo
  ros2 launch move_the_bot bringup.launch.py hardware:=isaac
"""
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState

START = {
    "shoulder_pan": 0.0, "shoulder_lift": -0.79, "elbow_flex": 0.31,
    "wrist_flex": 1.52, "wrist_roll": 0.0, "gripper": 1.0,
}
RATE = 60.0           # Hz
FOLLOW = 0.5          # share of the remaining error removed per step


class JointEcho(Node):
    def __init__(self):
        super().__init__("joint_echo")
        self.declare_parameter("joint_commands_topic", "/isaac_joint_commands")
        self.declare_parameter("joint_states_topic", "/isaac_joint_states")
        self.position = dict(START)
        self.target = dict(START)
        self.velocity = {name: 0.0 for name in START}
        self.create_subscription(
            JointState, self.get_parameter("joint_commands_topic").value, self._on_command, 10)
        self.publisher = self.create_publisher(
            JointState, self.get_parameter("joint_states_topic").value, 10)
        self.create_timer(1.0 / RATE, self._step)
        self.get_logger().info("Echoing joint commands as joint states (stand-in for Isaac Sim)")

    def _on_command(self, msg: JointState) -> None:
        for name, position in zip(msg.name, msg.position):
            if name in self.target and position == position:      # skip NaN
                self.target[name] = position

    def _step(self) -> None:
        for name in self.position:
            step = FOLLOW * (self.target[name] - self.position[name])
            self.velocity[name] = step * RATE
            self.position[name] += step
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = list(self.position)
        msg.position = [self.position[n] for n in msg.name]
        msg.velocity = [self.velocity[n] for n in msg.name]
        self.publisher.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = JointEcho()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
