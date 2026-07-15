import json
import re
import requests
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Point, PoseStamped
from std_msgs.msg import Header, String

from constants import (BUILTIN_OBJECTS, EXAMPLES, LLM_ONLY, MIDDLE,
                       OLLAMA_MODEL, OLLAMA_URL, POSITION_KEYWORDS,
                       SYSTEM_PROMPT)


def threejs_to_ik(x, y, z):
    """Convert Three.js (x=right, y=up, z=toward-viewer) to IK (x=forward, y=left, z=up)."""
    return (z, x, y)


def extract_numbers(text):
    return [float(x) for x in re.findall(r"-?\d+\.?\d*", text)]


def find_object(text):
    text_lower = text.lower()
    for obj in BUILTIN_OBJECTS:
        if obj in text_lower:
            return obj
    return None


def parse_voice_command(text, spawned_objects=None):
    t = text.lower().strip()

    if any(kw in t for kw in ["create ", "spawn ", "place ", "make ", "add ", "put ", "set "]):
        obj = find_object(t)
        if obj:
            nums = extract_numbers(t)
            if len(nums) >= 3:
                x, y, z = nums[0], nums[1], nums[2]
            else:
                x, y, z = MIDDLE
                for word, pos in POSITION_KEYWORDS.items():
                    if word in t:
                        x, y, z = pos
                        break
            return {"action": "spawn", "object": obj, "target": {"x": x, "y": y, "z": z}}

    if re.search(r"\b(grab|grasp|pick)\b", t):
        return {"action": "grasp"}
    if re.search(r"\b(put|release|drop)\b", t):
        return {"action": "release"}

    move_keywords = ["move", "go", "position", "teleport"]
    if any(kw in t for kw in move_keywords):
        nums = extract_numbers(t)
        if len(nums) >= 3:
            return {"action": "move_to", "target": {"x": nums[0], "y": nums[1], "z": nums[2]}}
        if spawned_objects:
            obj = find_object(t)
            if obj and obj in spawned_objects:
                return {"action": "move_to", "target": dict(spawned_objects[obj])}
            for name, pos in spawned_objects.items():
                if name in t:
                    return {"action": "move_to", "target": dict(pos)}
        for word, pos in POSITION_KEYWORDS.items():
            if word in t:
                return {"action": "move_to", "target": {"x": pos[0], "y": pos[1], "z": pos[2]}}
        if len(nums) == 1:
            return {"action": "move_to", "target": {"x": nums[0], "y": MIDDLE[1], "z": MIDDLE[2]}}
        return {"action": "move_to", "target": {"x": MIDDLE[0], "y": MIDDLE[1], "z": MIDDLE[2]}}

    if spawned_objects:
        obj = find_object(t)
        if obj and obj in spawned_objects:
            return {"action": "move_to", "target": dict(spawned_objects[obj])}
        for name, pos in spawned_objects.items():
            if name in t:
                return {"action": "move_to", "target": dict(pos)}

    return None


class AgenticCoreNode(Node):
    def __init__(self):
        super().__init__("agentic_core_node")
        self.goal_pub = self.create_publisher(PoseStamped, "/target_goal", 10)
        self.grasp_pub = self.create_publisher(String, "/grasp_command", 10)
        self.spawn_pub = self.create_publisher(String, "/object_spawn", 10)
        self.log_pub = self.create_publisher(String, "/agent_log", 10)

        self.sub_spatial = self.create_subscription(Point, "/spatial_coords", self.spatial_callback, 10)
        self.sub_voice = self.create_subscription(String, "/voice_commands", self.voice_callback, 10)

        self.current_pos = Point(x=0.0, y=0.3, z=0.15)
        self.current_voice = None
        self.spawned_objects = {}
        self.timer = self.create_timer(0.5, self.reasoning_loop)
        self.get_logger().info("Agentic Core Node started")

    def spatial_callback(self, msg):
        self.current_pos = msg

    def voice_callback(self, msg):
        self.current_voice = msg.data
        self.get_logger().info(f"Voice: {msg.data}")

    def query_ollama(self, prompt):
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "system": SYSTEM_PROMPT,
            "stream": False,
            "temperature": 0.1,
            "format": "json",
        }
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            self.get_logger().info(f"Ollama response: {data}")
            return data["response"]
        except Exception as e:
            self.get_logger().error(f"Ollama error: {e}")
            return None

    def _log(self, message):
        msg = String()
        msg.data = message
        self.log_pub.publish(msg)
        self.get_logger().info(message)

    def reasoning_loop(self):
        if self.current_voice is None:
            return

        voice = self.current_voice
        self.current_voice = None

        self._log(f'Voice: "{voice}"')

        action = None
        if not LLM_ONLY:
            action = parse_voice_command(voice, self.spawned_objects)
        if action is None:
            if LLM_ONLY:
                self._log("LLM_ONLY: skipping rule parser → querying LLM")
            else:
                self._log("Rule parser: no match → querying LLM")
            pos = self.current_pos or Point(x=0.0, y=0.3, z=0.15)
            obj_info = "Objects: " + ", ".join(
                f'"{n}" at ({p["x"]},{p["y"]},{p["z"]})' for n, p in self.spawned_objects.items()
            ) + "\n" if self.spawned_objects else ""
            obj_examples = "".join(
                f'  "move to {n}" → {{"action":"move_to","target":{{"x":{p["x"]},"y":{p["y"]},"z":{p["z"]}}}}}\n'
                for n, p in self.spawned_objects.items()
            )
            prompt = (
                f"Hand: ({pos.x:.3f},{pos.y:.3f},{pos.z:.3f})\n"
                f"{obj_info}"
                f'Voice: "{voice}"\n'
                f"Available: {', '.join(BUILTIN_OBJECTS)}\n"
                f"Position keywords: {' '.join(f'{k}=({v[0]},{v[1]},{v[2]})' for k, v in sorted(POSITION_KEYWORDS.items()))}\n"
                "Examples:\n"
                + "\n".join(f'  {v} → {j}' for v, j in EXAMPLES)
                + f"\n{obj_examples}"
                "JSON:"
            )
            response = self.query_ollama(prompt)
            if response is None:
                self._log("LLM: request failed")
                return
            self._log(f"LLM: {response}")
            try:
                action = json.loads(response.strip())
            except json.JSONDecodeError:
                self._log(f"LLM: failed to parse → {response}")
                return
        else:
            self._log(f"Rule parser: {json.dumps(action)}")

        self.execute_action(action)

    def _pub_str(self, publisher, data):
        msg = String()
        msg.data = data
        publisher.publish(msg)

    def execute_action(self, action):
        act = action.get("action", "none")
        if act == "move_to":
            target = action.get("target", {})
            try:
                tx = float(target.get("x", 0))
                ty = float(target.get("y", MIDDLE[1]))
                tz = float(target.get("z", MIDDLE[2]))
                ik_x, ik_y, ik_z = threejs_to_ik(tx, ty, tz)
                msg = PoseStamped()
                msg.header = Header()
                msg.header.stamp = self.get_clock().now().to_msg()
                msg.header.frame_id = "base_link"
                msg.pose.position.x = ik_x
                msg.pose.position.y = ik_y
                msg.pose.position.z = ik_z
                msg.pose.orientation.w = 1.0
                self.goal_pub.publish(msg)
                self._log(f"Action: move_to Three.js ({tx:.3f}, {ty:.3f}, {tz:.3f}) → IK ({ik_x:.3f}, {ik_y:.3f}, {ik_z:.3f})")
            except (TypeError, ValueError) as e:
                self._log(f"Action: bad move_to target → {e}")
        elif act == "grasp":
            self._pub_str(self.grasp_pub, "grasp")
            self._log("Action: grasp")
        elif act == "release":
            self._pub_str(self.grasp_pub, "release")
            self._log("Action: release")
        elif act == "spawn":
            obj = action.get("object", "unknown")
            target = action.get("target", {"x": MIDDLE[0], "y": MIDDLE[1], "z": MIDDLE[2]})
            try:
                x = float(target.get("x", MIDDLE[0]))
                y = float(target.get("y", MIDDLE[1]))
                z = float(target.get("z", MIDDLE[2]))
                self.spawned_objects[obj] = {"x": x, "y": y, "z": z}
                self._pub_str(self.spawn_pub, json.dumps({"name": obj, "x": x, "y": y, "z": z}))
                self._log(f"Action: spawn {obj} at ({x:.3f}, {y:.3f}, {z:.3f})")
            except (TypeError, ValueError) as e:
                self._log(f"Action: bad spawn data → {e}")
        elif act == "stop":
            self._log("Action: stop")
        elif act == "none":
            self._log("Action: none")


def main(args=None):
    rclpy.init(args=args)
    node = AgenticCoreNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
