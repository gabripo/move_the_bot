import rclpy
from rclpy.node import Node
from visualization_msgs.msg import Marker, MarkerArray
from std_msgs.msg import ColorRGBA


class VirtualSceneNode(Node):
    def __init__(self):
        super().__init__("virtual_scene_node")
        self.pub = self.create_publisher(MarkerArray, "/visualization_marker_array", 10)
        self.timer = self.create_timer(1.0, self.publish_scene)
        self.get_logger().info("Virtual Scene Node started")

    def publish_scene(self):
        markers = MarkerArray()

        table = Marker()
        table.header.frame_id = "base_link"
        table.header.stamp = self.get_clock().now().to_msg()
        table.ns = "scene"
        table.id = 0
        table.type = Marker.CUBE
        table.action = Marker.ADD
        table.pose.position.x = 0.20
        table.pose.position.y = 0.0
        table.pose.position.z = -0.02
        table.pose.orientation.w = 1.0
        table.scale.x = 0.60
        table.scale.y = 0.40
        table.scale.z = 0.02
        table.color = ColorRGBA(r=0.6, g=0.4, b=0.2, a=0.8)
        table.lifetime.sec = 0
        markers.markers.append(table)

        self.pub.publish(markers)


def main(args=None):
    rclpy.init(args=args)
    node = VirtualSceneNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
