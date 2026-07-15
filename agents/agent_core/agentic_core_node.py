import json
import time
import requests
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Point, PoseStamped
from std_msgs.msg import Bool, Header, String

from constants import (BUILTIN_OBJECTS, MIDDLE, OLLAMA_MODEL, OLLAMA_URL,
                       SPLIT_PROMPT, SYSTEM_PROMPT)
from tools import parse_voice_command, split_commands


def threejs_to_ik(x, y, z):
    return (z, x, y)


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
        msg.data = self.llm_only_toggle
        self.llm_only_state_pub.publish(msg)

    def _chat(self, messages):
        payload = {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "temperature": 0.1,
            "format": "json",
        }
        try:
            url = OLLAMA_URL.replace("/api/generate", "/api/chat")
            resp = requests.post(url, json=payload, timeout=600)
            resp.raise_for_status()
            return resp.json()["message"]
        except Exception as e:
            self.get_logger().error(f"Ollama chat error: {e}")
            return None

    def timer_tick(self):
        self._publish_llm_state()
        self.reasoning_loop()

    def _log(self, message):
        msg = String()
        msg.data = message
        self.log_pub.publish(msg)
        self.get_logger().info(message)

    def _llm_split(self, voice):
        msg = self._chat([
            {"role": "system", "content": SPLIT_PROMPT},
            {"role": "user", "content": f'Input: "{voice}"\nOutput:'},
        ])
        if not msg or not msg.get("content"):
            return None
        try:
            parts = json.loads(msg["content"].strip())
            if isinstance(parts, list) and len(parts) > 0 and all(isinstance(s, str) for s in parts):
                return parts
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    def reasoning_loop(self):
        if self.current_voice is None:
            return

        voice = self.current_voice
        self.current_voice = None

        self._log(f"Voice: {voice}")

        sub_commands = self._llm_split(voice)
        if sub_commands is not None:
            self._log(f"LLM split: {sub_commands}")
        else:
            sub_commands = split_commands(voice)
            self._log(f"Regex split: {sub_commands}")

        actions = []
        unparsed = []
        for cmd in sub_commands:
            action = parse_voice_command(cmd, self.spawned_objects)
            if action is not None:
                self._log(f"Parser: {json.dumps(action)}")
                actions.append(action)
            else:
                self._log(f"Parser: no match for \"{cmd}\"")
                unparsed.append(cmd)

        if unparsed:
            self._log(f"Querying LLM for: {unparsed}")
            pos = self.current_pos or Point(x=0.0, y=0.3, z=0.15)
            obj_info = "Objects: " + ", ".join(
                f'"{n}" at ({p["x"]},{p["y"]},{p["z"]})' for n, p in self.spawned_objects.items()
            ) + "\n" if self.spawned_objects else ""
            cmd_text = "\n".join(f'  "{c}"' for c in unparsed)
            prompt = (
                f"Hand: ({pos.x:.3f}, {pos.y:.3f}, {pos.z:.3f})\n"
                f"{obj_info}"
                f"The rule parser could not handle these sub-commands:\n{cmd_text}\n"
                "Generate the action(s) for each. Return a JSON array of action objects."
            )
            msg = self._chat([
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ])
            if msg and msg.get("content"):
                content = msg["content"].strip()
                self._log(f"LLM: {content}")
                try:
                    extra = json.loads(content)
                    if isinstance(extra, list):
                        actions.extend(extra)
                    else:
                        actions.append(extra)
                except json.JSONDecodeError:
                    self._log(f"LLM: failed to parse → {content}")

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
