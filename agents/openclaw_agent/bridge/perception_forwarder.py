import json
import os
import subprocess
import threading
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Point
from std_msgs.msg import String

BRIDGE_SCRIPT = "/app/bridge/dist/forwarder_bridge.js"


class PerceptionForwarder(Node):
    """ROS 2 node that forwards perception data to OpenClaw Gateway.

    Uses the openclaw-sdk via a Node.js bridge process (stdin/stdout).
    Set OPENCLAW_FORWARDER_BACKEND=websocket to use the direct WebSocket
    implementation instead.
    """

    def __init__(self):
        super().__init__("perception_forwarder")
        self.bridge_process = None
        self._start_bridge()

        self.sub_coords = self.create_subscription(
            Point, "/spatial_coords", self.on_coords, 10
        )
        self.sub_voice = self.create_subscription(
            String, "/voice_commands", self.on_voice, 10
        )
        self.get_logger().info("Perception Forwarder (SDK backend) started")

    def _start_bridge(self):
        self.bridge_process = subprocess.Popen(
            ["node", BRIDGE_SCRIPT],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        threading.Thread(target=self._read_output, daemon=True).start()
        threading.Thread(target=self._read_errors, daemon=True).start()
        self.get_logger().info("Node.js bridge process started")

    def _read_output(self):
        for line in self.bridge_process.stdout:
            line = line.strip()
            if line:
                try:
                    resp = json.loads(line)
                    self.get_logger().info(f"Agent: {resp}")
                except json.JSONDecodeError:
                    self.get_logger().info(f"Bridge: {line}")

    def _read_errors(self):
        for line in self.bridge_process.stderr:
            line = line.strip()
            if line:
                self.get_logger().info(f"Bridge: {line}")

    def _send(self, payload):
        if self.bridge_process and self.bridge_process.stdin:
            self.bridge_process.stdin.write(payload + "\n")
            self.bridge_process.stdin.flush()

    def on_coords(self, msg):
        payload = json.dumps({
            "type": "context",
            "data": f"Hand at ({msg.x:.3f}, {msg.y:.3f}, {msg.z:.3f})",
        })
        self._send(payload)

    def on_voice(self, msg):
        payload = json.dumps({"type": "task", "data": msg.data})
        self._send(payload)


def main(args=None):
    rclpy.init(args=args)
    node = PerceptionForwarder()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
