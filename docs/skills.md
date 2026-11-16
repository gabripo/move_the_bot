# Skills

Skills are the robot's vocabulary. Everything that moves the robot (the language rules, the
language model, your own script) does it by sending skill requests.

A request is a JSON object on the topic `/skill/request`:

```json
{"id": "42", "skill": "pick", "object": "apple"}
```

`id` is optional; it comes back in the answers on `/skill/status`:

```json
{"id": "42", "skill": "pick", "state": "running", "message": ""}
{"id": "42", "skill": "pick", "state": "succeeded", "message": "holding the apple"}
```

Requests are executed one at a time, in the order they arrive.

## The skills

| Skill | Fields | What it does |
|---|---|---|
| `spawn` | `object`, `at` (optional) | Creates an object on the table: `"apple"`, `"red cube"`. |
| `pick` | `object` | Moves to the object and grasps it. |
| `place` | `at` (optional) | Puts the held object down; without `at`, straight below. |
| `move_to` | `at`, `height` (optional) | Moves the gripper above a place without grasping. |
| `move_by` | `dx`, `dy`, `dz` | Moves the gripper relative to where it is, in metres. |
| `gripper` | `state`: `open` or `close` | Closing around an object picks it up. |
| `home` | | Returns to the home pose. |
| `remove` | `object` | Deletes an object. |
| `reset` | | Removes all objects, opens the gripper, goes home. |
| `stop` | | Stops the motion in progress and drops everything queued. |

### Places

`at` is one of:

```json
{"position": "left"}
{"object": "cube", "relation": "on"}
{"x": 0.22, "y": 0.10}
{"hand": true}
```

- **Positions**: `center`, `left`, `right`, `front`, `back`, `front left`, `front right`, `back left`, `back right`.
- **Relations**: `on`, `above`, `left_of`, `right_of`, `in_front_of`, `behind`, `next_to`.
- **Coordinates** are in metres in the robot's frame (x forward, y left). Points outside the
  arm's reach are pulled back inside it.
- **`hand`** is where the user's hand points during hand control.

If a place is taken, the nearest free spot is used.

### Objects

Built in: `apple`, `orange`, `ball`, `cube`, `can`, `mug`, `bottle`, `cylinder`. Put a colour
in front for a plain coloured shape: `"green cube"`, `"blue ball"`. Common other names work too
(`box`, `cup`, `soda can`).

Anything else is created as a small box. With a `SKETCHFAB_API_KEY` in `.env`, a matching 3D
model is downloaded and shown instead.

## Calling skills from your own code

From a shell inside the robot container (`docker compose exec robot /ros_entrypoint.sh bash`):

```bash
ros2 topic pub --once /skill/request std_msgs/String \
  '{data: "{\"skill\": \"spawn\", \"object\": \"apple\"}"}'
ros2 topic pub --once /skill/request std_msgs/String \
  '{data: "{\"skill\": \"pick\", \"object\": \"apple\"}"}'
ros2 topic echo /skill/status
```

From Python:

```python
import json, rclpy
from rclpy.node import Node
from std_msgs.msg import String

rclpy.init()
node = Node("my_planner")
requests = node.create_publisher(String, "/skill/request", 10)
node.create_subscription(String, "/skill/status", lambda m: print(json.loads(m.data)), 10)

def send(**skill):
    requests.publish(String(data=json.dumps(skill)))

send(skill="spawn", object="red cube", at={"position": "left"})
send(skill="pick", object="red cube")
send(skill="place", at={"position": "right"})
rclpy.spin(node)
```

From outside ROS (any language): open a websocket to `ws://localhost:9090` and speak the
[rosbridge protocol](https://github.com/RobotWebTools/rosbridge_suite/blob/ros2/ROSBRIDGE_PROTOCOL.md);
`web/js/ros.js` is an 80-line example.

This is also the place to plug in another planner: an agent framework, a behaviour tree, or a
vision-language model that outputs skills.

## Plain-language commands

The topic `/voice_commands` takes sentences instead of JSON. The rules in `language.py` cover:

| You say | Skills |
|---|---|
| "create an apple and a red cube on the left" | `spawn`, `spawn` |
| "grab the apple" · "pick it up" | `pick` |
| "put it on the cube" · "drop it" | `place` |
| "move the mug to the front" | `pick`, `place` |
| "pick up the apple and put it next to the mug, then go home" | `pick`, `place`, `home` |
| "move up 5 cm" · "a bit to the left" | `move_by` |
| "go to the apple" · "move to the left" | `move_to` |
| "open the gripper" · "go home" · "clear the table" · "stop" | `gripper`, `home`, `reset`, `stop` |

Anything the rules do not fully understand goes to the language model with the list of skills,
the objects on the table and their positions. Its answer is validated by the same code that
checks every other request, so a wrong answer becomes an error message, not a wrong motion.

## Adding a skill

1. Describe it in `SKILLS` and check its fields in `validate()` (`move_the_bot/skills.py`).
   The description is also what the language model reads.
2. Write `_skill_<name>(self, request)` in `skill_server.py` and add it to `handlers` in
   `_worker()`. Use `self._solve(...)` for inverse kinematics and `self._move_joints(...)` for a
   planned motion; raise `SkillError("...")` with a message the user can act on.
3. Optionally add a rule in `language.py` so it works without the model.
4. Add tests: `tests/unit/test_skills.py`, `tests/unit/test_language.py`, `tests/e2e/test_robot.py`.

## Adding an object

Add a line to `CATALOGUE` in `move_the_bot/world.py` (shape, size in metres, colour) and run
`python3 scripts/make_models.py` to generate its 3D model. The size you give is used for
drawing, for grasping and for collision checking.

To draw an object with your own 3D model, for example one made from a photo of your mug, see
[your-own-objects.md](your-own-objects.md).
