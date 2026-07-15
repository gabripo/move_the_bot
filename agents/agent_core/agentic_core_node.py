import json
import re
import time
import requests
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Point, PoseStamped
from std_msgs.msg import Bool, Header, String

from constants import (BREAKDOWN_PROMPT, BUILTIN_OBJECTS, EXAMPLES, LLM_ONLY,
                       MIDDLE, OLLAMA_MODEL, OLLAMA_URL,
                       POSITIONAL_QUALIFIERS, POSITION_KEYWORDS,
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


def resolve_position(text):
    t = text.lower()
    for word, pos in POSITION_KEYWORDS.items():
        if word in t:
            return pos
    for phrase, keyword in POSITIONAL_QUALIFIERS.items():
        if phrase in t:
            return POSITION_KEYWORDS[keyword]
    return None


def parse_voice_command(text, spawned_objects=None):
    t = text.lower().strip()

    if any(kw in t for kw in ["create ", "spawn ", "place ", "make ", "add ", "put ", "set ", "introduce "]):
        obj = find_object(t)
        if obj:
            nums = extract_numbers(t)
            if len(nums) >= 3:
                x, y, z = nums[0], nums[1], nums[2]
            else:
                x, y, z = resolve_position(t) or MIDDLE
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
        pos = resolve_position(t)
        if pos:
            return {"action": "move_to", "target": {"x": pos[0], "y": pos[1], "z": pos[2]}}
        if spawned_objects and re.search(r"\b(it|them)\b", t):
            last = list(spawned_objects.keys())[-1]
            return {"action": "move_to", "target": dict(spawned_objects[last])}
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
        self.sub_toggle = self.create_subscription(Bool, "/llm_only_toggle", self.toggle_callback, 10)

        self.llm_only_state_pub = self.create_publisher(Bool, "/llm_only_state", 10)
        self.llm_only_toggle = False
        self._publish_llm_state()

        self.current_pos = Point(x=0.0, y=0.3, z=0.15)
        self.current_voice = None
        self.spawned_objects = {}
        self.timer = self.create_timer(0.5, self.timer_tick)
        self.get_logger().info("Agentic Core Node started")

    def spatial_callback(self, msg):
        self.current_pos = msg

    def voice_callback(self, msg):
        self.current_voice = msg.data
        self.get_logger().info(f"Voice: {msg.data}")

    def toggle_callback(self, msg):
        self.llm_only_toggle = msg.data
        self._publish_llm_state()
        self.get_logger().info(f"LLM toggle: {self.llm_only_toggle}")

    def _publish_llm_state(self):
        msg = Bool()
        msg.data = LLM_ONLY
        self.llm_only_state_pub.publish(msg)

    def query_ollama(self, prompt, system=None):
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "system": system or SYSTEM_PROMPT,
            "stream": False,
            "temperature": 0.1,
            "format": "json",
        }
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=600)
            resp.raise_for_status()
            data = resp.json()
            # self.get_logger().info(f"Ollama response: {data}")
            return data["response"]
        except Exception as e:
            self.get_logger().error(f"Ollama error: {e}")
            return None

    def timer_tick(self):
        self._publish_llm_state()
        self.reasoning_loop()

    def _log(self, message):
        msg = String()
        msg.data = message
        self.log_pub.publish(msg)
        self.get_logger().info(message)

    @staticmethod
    def _dict_to_string(d):
        act = d.get("action", "")
        if act == "spawn":
            return f"create {d.get('object', 'object')}"
        if act == "move_to":
            return "move"
        if act == "grasp":
            return "grasp"
        if act == "release":
            return "release"
        return ""

    def _breakdown_command(self, voice):
        self._log("LLM: breaking down command")
        response = self.query_ollama(
            f'Voice: "{voice}"\nJSON:', system=BREAKDOWN_PROMPT
        )
        if response is None:
            return [voice]
        try:
            parts = json.loads(response.strip())
            if isinstance(parts, list) and len(parts) > 0:
                if all(isinstance(s, str) for s in parts):
                    return parts
                if all(isinstance(d, dict) for d in parts):
                    strings = [self._dict_to_string(d) for d in parts if self._dict_to_string(d)]
                    return strings if strings else [voice]
            if isinstance(parts, dict) and len(parts) > 0:
                for val in parts.values():
                    if isinstance(val, list) and len(val) > 0:
                        if all(isinstance(s, str) for s in val):
                            return val
                        if all(isinstance(d, dict) for d in val):
                            strings = [self._dict_to_string(d) for d in val if self._dict_to_string(d)]
                            return strings if strings else [voice]
                return list(parts.keys())
            self._log(f"LLM: unexpected breakdown format → {response}")
            return [voice]
        except (json.JSONDecodeError, TypeError):
            self._log(f"LLM: failed to parse breakdown → {response}")
            return [voice]

    def _query_llm_for_action(self, cmd):
        pos = self.current_pos or Point(x=0.0, y=0.3, z=0.15)
        obj_info = "Objects: " + ", ".join(
            f'"{n}" at ({p["x"]},{p["y"]},{p["z"]})' for n, p in self.spawned_objects.items()
        ) + "\n" if self.spawned_objects else ""
        prompt = (
            f"Hand: ({pos.x:.3f}, {pos.y:.3f}, {pos.z:.3f})\n"
            f"{obj_info}"
            f'Voice: "{cmd}"\n'
            "JSON:"
        )
        response = self.query_ollama(prompt)
        if response is None:
            self._log("LLM: request failed for action generation")
            return None
        self._log(f"LLM: {response}")
        try:
            return json.loads(response.strip())
        except json.JSONDecodeError:
            self._log(f"LLM: failed to parse → {response}")
            return None

    def reasoning_loop(self):
        if self.current_voice is None:
            return

        voice = self.current_voice
        self.current_voice = None

        self._log(f"Voice: {voice}")

        sub_commands = self._breakdown_command(voice)
        self._log(f"Sub-commands: {sub_commands}")

        actions = []
        for cmd in sub_commands:
            use_llm = LLM_ONLY or self.llm_only_toggle
            action = None
            if not use_llm:
                action = parse_voice_command(cmd, self.spawned_objects)
            if action is not None:
                if use_llm:
                    self._log("Rule parser result (LLM_ONLY mode)")
                else:
                    self._log(f"Rule parser: {json.dumps(action)}")
                if isinstance(action, list):
                    actions.extend(action)
                else:
                    actions.append(action)
            else:
                if use_llm:
                    self._log("LLM_ONLY: querying LLM")
                else:
                    self._log("Rule parser: no match → querying LLM")
                action = self._query_llm_for_action(cmd)
                if action is not None:
                    if isinstance(action, list):
                        actions.extend(action)
                    else:
                        actions.append(action)

        if not actions:
            self._log("No actions to execute")
            return
        if len(actions) == 1:
            self.execute_actions(actions[0])
        else:
            self.execute_actions(actions)

    def _pub_str(self, publisher, data):
        msg = String()
        msg.data = data
        publisher.publish(msg)

    def execute_actions(self, actions):
        if isinstance(actions, list):
            for i, action in enumerate(actions):
                self._log(f"Step {i+1}/{len(actions)}")
                self.execute_action(action)
                if i < len(actions) - 1:
                    time.sleep(3.0)
        else:
            self.execute_action(actions)

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
                path = f"/models/builtin/{obj}.glb" if obj in BUILTIN_OBJECTS else ""
                self._pub_str(self.spawn_pub, json.dumps({"name": obj, "path": path, "x": x, "y": y, "z": z}))
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
