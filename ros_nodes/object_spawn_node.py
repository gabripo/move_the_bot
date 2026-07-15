import json
import os
import shutil
import rclpy
from pathlib import Path
from rclpy.node import Node
from std_msgs.msg import String
from visualization_msgs.msg import Marker, MarkerArray
from geometry_msgs.msg import Point
from models.lookup import lookup


def threejs_to_ik(x, y, z):
    return (z, x, y)


class ObjectSpawnNode(Node):
    def __init__(self):
        super().__init__("object_spawn_node")
        self.sub = self.create_subscription(String, "/object_spawn", self.on_spawn, 10)
        self.reset_sub = self.create_subscription(String, "/reset_command", self.reset_callback, 10)
        self.marker_pub = self.create_publisher(MarkerArray, "/visualization_marker_array", 10)
        self.notify_pub = self.create_publisher(String, "/object_spawn_notify", 10)
        self.spawned_ids = {}
        self.next_id = 1
        self.get_logger().info("Object Spawn Node started")

    @staticmethod
    def _to_web_path(file_path):
        idx = file_path.find("/models/")
        return file_path[idx:] if idx >= 0 else ""

    def reset_callback(self, msg: String):
        if msg.data == "clear_cache":
            cache = Path(os.environ.get("MODEL_CACHE_DIR", "/models/cache"))
            count = 0
            for f in cache.glob("*"):
                if f.is_file() and f.suffix in (".glb", ".gltf"):
                    f.unlink()
                    count += 1
            self.get_logger().info(f"Cleared {count} model(s) from cache")
            return
        if msg.data != "reset":
            return
        self.get_logger().info("Clearing spawned objects")
        array = MarkerArray()
        for name, obj_id in list(self.spawned_ids.items()):
            marker = Marker()
            marker.header.frame_id = "base_link"
            marker.header.stamp = self.get_clock().now().to_msg()
            marker.ns = "spawned_objects"
            marker.id = obj_id
            marker.action = Marker.DELETE
            array.markers.append(marker)
        self.spawned_ids.clear()
        if array.markers:
            self.marker_pub.publish(array)

    def on_spawn(self, msg):
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError as e:
            self.get_logger().error(f"Invalid JSON: {e}")
            return

        name = data.get("name", "unknown")
        x = float(data.get("x", 0.2))
        y = float(data.get("y", 0.0))
        z = float(data.get("z", 0.05))
        path = data.get("path", "")

        if path and os.path.exists(path):
            model_path = path
            source = "provided"
        else:
            result = lookup(name)
            if result is None:
                self.get_logger().warn(f"No 3D model found for '{name}'")
                self._publish_error(f"No 3D model found for '{name}'")
                return
            model_path, source = result

        scale = 0.15 if source in ("sketchfab", "cache") else 1.0
        web_path = self._to_web_path(model_path) if model_path else ""
        notify = String()
        notify.data = json.dumps({"name": name, "path": web_path, "x": x, "y": y, "z": z, "scale": scale})
        self.notify_pub.publish(notify)

        self.spawned_ids[name] = self.spawned_ids.get(name, self.next_id)
        if self.spawned_ids[name] == self.next_id:
            self.next_id += 1

        ik_x, ik_y, ik_z = threejs_to_ik(x, y, z)
        marker = Marker()
        marker.header.frame_id = "base_link"
        marker.header.stamp = self.get_clock().now().to_msg()
        marker.ns = "spawned_objects"
        marker.id = self.spawned_ids[name]
        marker.type = Marker.MESH_RESOURCE
        marker.action = Marker.ADD
        marker.mesh_resource = f"file://{model_path}"
        marker.mesh_use_embedded_materials = True
        marker.pose.position = Point(x=ik_x, y=ik_y, z=ik_z)
        marker.pose.orientation.w = 1.0
        marker.scale.x = scale
        marker.scale.y = scale
        marker.scale.z = scale
        marker.color.a = 1.0
        marker.color.r = 1.0
        marker.color.g = 1.0
        marker.color.b = 1.0
        marker.lifetime.sec = 0

        array = MarkerArray()
        array.markers.append(marker)
        self.marker_pub.publish(array)
        self.get_logger().info(f"Spawned '{name}' at ({x}, {y}, {z}) from {source}")

    def _publish_error(self, message):
        array = MarkerArray()
        err = Marker()
        err.header.frame_id = "base_link"
        err.header.stamp = self.get_clock().now().to_msg()
        err.ns = "spawned_objects"
        err.id = 9999
        err.type = Marker.TEXT_VIEW_FACING
        err.action = Marker.ADD
        err.pose.position.x = 0.0
        err.pose.position.y = 0.0
        err.pose.position.z = 0.3
        err.scale.z = 0.05
        err.color = ColorRGBA(r=1.0, g=0.0, b=0.0, a=1.0)
        err.text = message
        err.lifetime.sec = 5
        array.markers.append(err)
        self.marker_pub.publish(array)


from std_msgs.msg import ColorRGBA


def main(args=None):
    rclpy.init(args=args)
    node = ObjectSpawnNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
