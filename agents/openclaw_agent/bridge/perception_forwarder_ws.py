import json
import os
import threading
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Point
from std_msgs.msg import String
import websocket

GATEWAY_URL = os.environ.get("OPENCLAW_GATEWAY_URL", "ws://openclaw:1455")
AGENT_ID = os.environ.get("OPENCLAW_AGENT_ID", "main")


class PerceptionForwarderWS(Node):
    """ROS 2 node that forwards perception data to OpenClaw Gateway.

    Uses direct WebSocket connection to the Gateway protocol.
    This is an alternative to the SDK-based forwarder, selected via:
      OPENCLAW_FORWARDER_BACKEND=websocket
    """

    def __init__(self):
        super().__init__("perception_forwarder_ws")
        self.ws = None
        self.connected = False
        self._connect_ws()

        self.sub_coords = self.create_subscription(
            Point, "/spatial_coords", self.on_coords, 10
        )
        self.sub_voice = self.create_subscription(
            String, "/voice_commands", self.on_voice, 10
        )
        self.get_logger().info(f"Perception Forwarder (WS backend) started -> {GATEWAY_URL}")

    def _connect_ws(self):
        try:
            self.ws = websocket.WebSocket()
            self.ws.connect(GATEWAY_URL, timeout=5)
            self.connected = True
            self.get_logger().info("Connected to Gateway via WebSocket")
            threading.Thread(target=self._listen, daemon=True).start()
        except Exception as e:
            self.get_logger().error(f"WebSocket connection failed: {e}")
            self.connected = False

    def _listen(self):
        while self.connected:
            try:
                msg = self.ws.recv()
                if msg:
                    self.get_logger().info(f"Gateway: {msg}")
            except Exception:
                self.connected = False
                break

    def _send(self, payload):
        if not self.connected:
            self._connect_ws()
        if self.connected and self.ws:
            try:
                # Gateway RPC format: {"op": "send", "agent": "main", "message": "..."}
                rpc = {
                    "op": "send",
                    "agent": AGENT_ID,
                    "message": payload,
                }
                self.ws.send(json.dumps(rpc))
            except Exception as e:
                self.get_logger().error(f"Send error: {e}")
                self.connected = False

    def on_coords(self, msg):
        text = f"Hand at ({msg.x:.3f}, {msg.y:.3f}, {msg.z:.3f})"
        self._send({"type": "context", "data": text})

    def on_voice(self, msg):
        self._send({"type": "task", "data": msg.data})


def main(args=None):
    rclpy.init(args=args)
    node = PerceptionForwarderWS()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
