"""The language agent: a sentence in, robot skills out.

  /voice_commands  (std_msgs/String)        what the user typed or said
  /agent/llm_only  (std_msgs/Bool)          skip the rules and always ask the language model
  /agent_log       (std_msgs/String, JSON)  {"role": "user" | "robot" | "info" | "error", "text": "..."}
  /agent/state     (std_msgs/String, JSON)  model name, whether it is ready, whether the agent is busy

A command first goes through the rules in language.py (instant). Only if they do not understand
it is the language model asked (llm.py). Either way the result is a list of skill requests,
which are sent to the skill server one at a time, waiting for each to finish.
"""
from __future__ import annotations

import json
import queue
import threading
import time
import uuid

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import Bool, String

from . import language, llm
from .skills import describe
from .world import World

SKILL_TIMEOUT = 90.0


class Agent(Node):
    def __init__(self):
        super().__init__("agent")
        self.commands = queue.Queue()
        self.results = {}                   # request id -> final status
        self.result_event = threading.Event()
        self.scene = []
        self.held = None
        self.hand = None
        self.last_object = None
        self.llm_only = False
        self.llm_ready = llm.BACKEND == "openai"
        self.llm_error = ""
        self.busy = False
        self.abort = threading.Event()

        group = ReentrantCallbackGroup()
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.request_pub = self.create_publisher(String, "/skill/request", 50)
        self.log_pub = self.create_publisher(String, "/agent_log", 50)
        self.state_pub = self.create_publisher(String, "/agent/state", latched)
        self.create_subscription(String, "/voice_commands", self._on_command, 20, callback_group=group)
        self.create_subscription(Bool, "/agent/llm_only", self._on_llm_only, 5, callback_group=group)
        self.create_subscription(String, "/scene/objects", self._on_scene, latched, callback_group=group)
        self.create_subscription(String, "/skill/status", self._on_status, 50, callback_group=group)
        self.create_subscription(String, "/skill/state", self._on_skill_state, 5, callback_group=group)
        self.create_timer(1.0, self._publish_state, callback_group=group)

        threading.Thread(target=self._worker, daemon=True).start()
        threading.Thread(target=self._warm_up, daemon=True).start()
        self.get_logger().info(f"Agent started (model: {llm.BACKEND} / {llm.model_name()})")

    # ------------------------------------------------------------- plumbing

    def _log(self, role: str, text: str) -> None:
        self.log_pub.publish(String(data=json.dumps({"role": role, "text": text})))
        self.get_logger().info(f"{role}: {text}")

    def _publish_state(self) -> None:
        self.state_pub.publish(String(data=json.dumps({
            "llm_only": self.llm_only, "backend": llm.BACKEND, "model": llm.model_name(),
            "llm_ready": self.llm_ready, "llm_error": self.llm_error, "busy": self.busy,
        })))

    def _warm_up(self) -> None:
        """Make sure the model is there (Ollama downloads it the first time: a few minutes)."""
        if llm.BACKEND == "openai":
            return
        while rclpy.ok() and not self.llm_ready:
            error = llm.warm_up()
            if error is None:
                self.llm_ready, self.llm_error = True, ""
                self._log("info", f"Language model ready: {llm.model_name()}")
            else:
                self.llm_error = error
                time.sleep(10.0)
            self._publish_state()

    def _on_llm_only(self, msg: Bool) -> None:
        self.llm_only = bool(msg.data)
        self._publish_state()

    def _on_scene(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
            self.scene, self.held = data.get("objects", []), data.get("held")
        except json.JSONDecodeError:
            pass

    def _on_skill_state(self, msg: String) -> None:
        try:
            self.hand = json.loads(msg.data).get("hand")
        except json.JSONDecodeError:
            pass

    def _on_status(self, msg: String) -> None:
        try:
            status = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        if status.get("state") in ("succeeded", "failed", "stopped"):
            self.results[status.get("id", "")] = status
            self.result_event.set()

    def _on_command(self, msg: String) -> None:
        text = " ".join(msg.data.split())
        if not text:
            return
        # "stop" must not wait behind the motion it is meant to stop.
        if language.parse(text) == [{"skill": "stop"}]:
            self._log("user", text)
            self.abort.set()
            while not self.commands.empty():
                try:
                    self.commands.get_nowait()
                except queue.Empty:
                    break
            self.request_pub.publish(String(data=json.dumps({"skill": "stop", "id": uuid.uuid4().hex[:8]})))
            self._log("robot", "Stopped.")
            return
        self.commands.put(text[:300])

    # ------------------------------------------------------------- thinking

    def _world(self) -> World:
        world = World.from_snapshot(self.scene)
        if self.last_object in world.objects:
            world.last = self.last_object
        elif world.objects:
            world.last = next(reversed(world.objects))
        return world

    def _understand(self, text: str) -> list | None:
        world = self._world()
        if not self.llm_only:
            skills = language.parse(text, world)
            if skills is not None:
                self._log("info", "Understood by the rules: " + " → ".join(describe(s) for s in skills))
                return skills
        self._log("info", f"Asking the language model ({llm.model_name()})…")
        started = time.monotonic()
        try:
            skills, say, problems = llm.ask(text, world, self.hand)
        except llm.LLMError as e:
            self._log("error", f"I did not understand that, and the language model did not help: {e}.")
            return None
        took = time.monotonic() - started
        for problem in problems:
            self._log("info", f"Ignored an invalid step from the model: {problem}")
        if skills:
            self._log("info", f"Model plan ({took:.1f} s): " + " → ".join(describe(s) for s in skills))
        if say:
            self._log("robot", say)
        elif not skills:
            self._log("robot", "I do not know how to do that.")
        return skills

    def _run(self, skill: dict) -> dict:
        """Send one skill to the skill server and wait until it is finished."""
        request = dict(skill, id=uuid.uuid4().hex[:8])
        self.request_pub.publish(String(data=json.dumps(request)))
        deadline = time.monotonic() + SKILL_TIMEOUT
        while time.monotonic() < deadline:
            if request["id"] in self.results:
                return self.results.pop(request["id"])
            if self.abort.is_set():
                return {"state": "stopped", "message": "stopped"}
            self.result_event.wait(0.1)
            self.result_event.clear()
        return {"state": "failed", "message": "the robot did not answer"}

    def _worker(self) -> None:
        while rclpy.ok():
            try:
                text = self.commands.get(timeout=0.2)
            except queue.Empty:
                continue
            self.abort.clear()
            self.busy = True
            self._publish_state()
            try:
                self._log("user", text)
                skills = self._understand(text)
                for skill in skills or []:
                    # Picking something while holding something else: put the first one down.
                    if skill["skill"] == "pick" and self.held and self._world().find(skill["object"]) \
                            and self._world().find(skill["object"]).name != self.held:
                        self._run({"skill": "place"})
                    result = self._run(skill)
                    if "object" in skill and skill["skill"] in ("spawn", "pick"):
                        found = self._world().find(skill["object"])
                        self.last_object = found.name if found else self.last_object
                    if result["state"] == "succeeded":
                        if skill["skill"] not in ("move_to", "move_by"):
                            self._log("robot", result.get("message", "done").capitalize() + ".")
                    elif result["state"] == "stopped":
                        break
                    else:
                        self._log("error", f"I could not {describe(skill)}: {result.get('message', 'unknown error')}.")
                        break
                    time.sleep(0.05)        # let the scene update arrive before the next step
            except Exception as e:  # noqa: BLE001  one bad command must not stop the agent
                self.get_logger().error(f"Agent error: {e!r}")
                self._log("error", f"Internal error: {e}")
            finally:
                self.busy = False
                self._publish_state()


def main(args=None):
    rclpy.init(args=args)
    node = Agent()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
