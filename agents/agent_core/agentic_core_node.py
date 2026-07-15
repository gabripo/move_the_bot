import json
import os
import re
import requests
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Point, PoseStamped
from std_msgs.msg import Header, String

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434/api/generate")
OLLAMA_MODEL = os.environ.get(
    "OLLAMA_MODEL",
    "llama3.2:3b-instruct-q4_K_M",
)
LLM_ONLY = os.environ.get("LLM_ONLY", "0") == "1"
# Recommended models (light → capable):
#   llama3.2:3b-instruct-q4_K_M  (fast, ~2 GB RAM)
#   llama3.2:3b-instruct-fp16    (more accurate, ~6 GB RAM)
#   llama3.2:3b                   (default, ~2 GB RAM)
#   llama3.1:8b-instruct-q4_K_M  (larger, ~4.5 GB RAM)
#   llama3.1:8b                   (~4.5 GB RAM, better reasoning)
#   llama3:70b-instruct-q2_K     (max capability, needs ~35 GB RAM)
# Model tag reference: https://ollama.com/library/llama3.2/tags
BUILTIN_OBJECTS = ["apple", "mug", "bottle", "cube", "sphere", "can", "cylinder", "table"]
# All positions are in Three.js frame: x=right, y=up, z=forward
MIDDLE = (0.0, 0.25, 0.25)

POSITION_KEYWORDS = {
    "left": (-0.15, 0.25, 0.15),
    "right": (0.15, 0.25, 0.15),
    "front": (0.0, 0.35, 0.15),
    "back": (0.0, 0.15, -0.15),
    "high": (0.0, 0.25, 0.15),
    "low": (0.0, 0.25, 0.05),
    "top": (0.0, 0.35, 0.15),
    "bottom": (0.0, 0.05, -0.15),
    "center": MIDDLE,
    "middle": MIDDLE,
}

WORKSPACE = {
    "x_min": -0.5, "x_max": 0.5,
    "y_min": 0.0, "y_max": 0.5,
    "z_min": 0.0, "z_max": 0.5,
}

def _build_system_prompt():
    pos_lines = []
    for kw, (x, y, z) in sorted(POSITION_KEYWORDS.items()):
        pos_lines.append(f'  "{kw}" → ({x:7.3f}, {y:.3f}, {z:.3f})')

    bkw = POSITION_KEYWORDS["back"]
    rkw = POSITION_KEYWORDS["right"]
    ckw = POSITION_KEYWORDS["center"]

    return (
        "You are a robot arm controller.\n"
        "\n"
        "ACTIONS:\n"
        '  move_to  → {"action":"move_to","target":{"x":float,"y":float,"z":float}}\n'
        '  grasp    → {"action":"grasp"}\n'
        '  release  → {"action":"release"}\n'
        '  spawn    → {"action":"spawn","object":"name","target":{"x":float,"y":float,"z":float}}\n'
        '  none     → {"action":"none"}\n'
        "\n"
        "AVAILABLE OBJECTS: apple, mug, bottle, cube, sphere, can, cylinder, table\n"
        "\n"
        f"WORKSPACE (Three.js frame: x=right, y=up, z=toward viewer):\n"
        f"  x ∈ [{WORKSPACE['x_min']}, {WORKSPACE['x_max']}], "
        f"y ∈ [{WORKSPACE['y_min']}, {WORKSPACE['y_max']}], "
        f"z ∈ [{WORKSPACE['z_min']}, {WORKSPACE['z_max']}]\n"
        f"  Center = {MIDDLE}\n"
        "\n"
        "POSITION KEYWORDS (map to these coordinates):\n"
        f"{chr(10).join(pos_lines)}\n"
        "\n"
        "RULES:\n"
        "- spawn: triggered by create/place/spawn/add/put/make + object name + optional position.\n"
        '  If position is a keyword like "right" or "left", use the coordinates above.\n'
        '  If position is "here" or unspecified, use the current Hand position.\n'
        "- move_to: triggered by move/go/reach. Extract explicit x y z numbers if given,\n"
        "  or use position keywords, or move to a named object.\n"
        "- grasp: triggered by grab/pick/take/get.\n"
        "- release: triggered by release/drop.\n"
        "\n"
        "EXAMPLES:\n"
        '  Voice: "move to 0.2 0.1 0.3"\n'
        '  JSON: {"action":"move_to","target":{"x":0.2,"y":0.1,"z":0.3}}\n'
        "\n"
        f'  Voice: "teleport the arm to the back"\n'
        f'  JSON: {{"action":"move_to","target":{{"x":{bkw[0]},"y":{bkw[1]},"z":{bkw[2]}}}}}\n'
        "\n"
        f'  Voice: "add a bottle to the right"\n'
        f'  JSON: {{"action":"spawn","object":"bottle","target":{{"x":{rkw[0]},"y":{rkw[1]},"z":{rkw[2]}}}}}\n'
        "\n"
        f'  Voice: "create apple at center"\n'
        f'  JSON: {{"action":"spawn","object":"apple","target":{{"x":{ckw[0]},"y":{ckw[1]},"z":{ckw[2]}}}}}\n'
        "\n"
        '  Voice: "grasp"\n'
        '  JSON: {"action":"grasp"}\n'
        "\n"
        '  Voice: "release"\n'
        '  JSON: {"action":"release"}\n'
        "\n"
        '  Voice: "do nothing"\n'
        '  JSON: {"action":"none"}'
    )

SYSTEM_PROMPT = _build_system_prompt()


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

    spawn_keywords = ["create ", "spawn ", "place ", "make ", "add ", "put ", "set "]
    spawn_matched = any(kw in t for kw in spawn_keywords)
    if spawn_matched:
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
            objects_info = ""
            if self.spawned_objects:
                objects_info = "Objects: " + ", ".join(
                    f'"{n}" at ({p["x"]},{p["y"]},{p["z"]})' for n, p in self.spawned_objects.items()
                ) + "\n"
            object_examples = ""
            if self.spawned_objects:
                for obj_name, obj_pos in self.spawned_objects.items():
                    object_examples += (
                        f'  "move to {obj_name}" → {{"action":"move_to",'
                        f'"target":{{"x":{obj_pos["x"]},"y":{obj_pos["y"]},"z":{obj_pos["z"]}}}}}\n'
                    )
            pos_kw_str = " ".join(
                f'{k}=({v[0]},{v[1]},{v[2]})'
                for k, v in sorted(POSITION_KEYWORDS.items())
            )
            prompt = (
                f"Hand: ({pos.x:.3f},{pos.y:.3f},{pos.z:.3f})\n"
                f"{objects_info}"
                f'Voice: "{voice}"\n'
                f"Position keywords: {pos_kw_str}\n"
                "Available objects: apple, mug, bottle, cube, sphere, can, cylinder\n"
                "Examples:\n"
                '  "move to 0.2 0.1 0.3" → {"action":"move_to","target":{"x":0.2,"y":0.1,"z":0.3}}\n'
                f'  "teleport the arm to the back" → {{"action":"move_to","target":{{"x":{POSITION_KEYWORDS["back"][0]},"y":{POSITION_KEYWORDS["back"][1]},"z":{POSITION_KEYWORDS["back"][2]}}}}}\n'
                f'  "add a bottle to the right" → {{"action":"spawn","object":"bottle","target":{{"x":{POSITION_KEYWORDS["right"][0]},"y":{POSITION_KEYWORDS["right"][1]},"z":{POSITION_KEYWORDS["right"][2]}}}}}\n'
                f"{object_examples}"
                '  "grasp" → {"action":"grasp"}\n'
                '  "release" → {"action":"release"}\n'
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
            msg = String()
            msg.data = "grasp"
            self.grasp_pub.publish(msg)
            self._log("Action: grasp")
        elif act == "release":
            msg = String()
            msg.data = "release"
            self.grasp_pub.publish(msg)
            self._log("Action: release")
        elif act == "spawn":
            obj = action.get("object", "unknown")
            target = action.get("target", {"x": MIDDLE[0], "y": MIDDLE[1], "z": MIDDLE[2]})
            try:
                x = float(target.get("x", MIDDLE[0]))
                y = float(target.get("y", MIDDLE[1]))
                z = float(target.get("z", MIDDLE[2]))
                self.spawned_objects[obj] = {"x": x, "y": y, "z": z}
                msg = String()
                msg.data = json.dumps({"name": obj, "x": x, "y": y, "z": z})
                self.spawn_pub.publish(msg)
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
