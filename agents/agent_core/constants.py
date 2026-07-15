import os

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434/api/generate")
OLLAMA_MODEL = os.environ.get(
    "OLLAMA_MODEL",
    "llama3.2:3b-instruct-q4_K_M",
)
LLM_ONLY = os.environ.get("LLM_ONLY", "0") == "1"

BUILTIN_OBJECTS = ["apple", "mug", "bottle", "cube", "sphere", "can", "cylinder", "table"]

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

BREAKDOWN_PROMPT = (
    "Split the user's command into separate simple commands. "
    "Each simple command must describe exactly one action (spawn, move_to, grasp, release, none). "
    'Use "and", "then", commas as split points. '
    "Repeat any missing verbs so each command is self-contained. "
    "Keep positional phrases (e.g. 'at its left', 'to the right', 'at center') attached to the sub-command they belong to. "
    "Do NOT generate extra move_to commands that were not explicitly said."
    " You MUST return a JSON array of plain text strings."
    " Never return JSON objects or dicts. Only a flat array of strings."
    "\nExamples:\n"
    '  "move to the apple, then to the bottle"\n'
    '    -> ["move to the apple", "move to the bottle"]\n'
    '  "create an apple and a mug"\n'
    '    -> ["create an apple", "create a mug"]\n'
    '  "create an apple and a bottle at its left"\n'
    '    -> ["create an apple", "create a bottle at its left"]\n'
    '  "grasp the bottle"\n'
    '    -> ["grasp"]\n'
    '  "spawn a bottle and move it to the right"\n'
    '    -> ["spawn a bottle", "move it to the right"]'
)

POSITIONAL_QUALIFIERS = {
    "left of": "left",
    "to the left": "left",
    "on the left": "left",
    "at its left": "left",
    "to its left": "left",
    "right of": "right",
    "to the right": "right",
    "on the right": "right",
    "front of": "front",
    "in front": "front",
    "back of": "back",
    "behind": "back",
    "above": "high",
    "over": "high",
    "below": "low",
    "under": "low",
    "bottom of": "bottom",
    "top of": "top",
}

EXAMPLES = [
    ('"move to 0.2 0.1 0.3"', '{"action":"move_to","target":{"x":0.2,"y":0.1,"z":0.3}}'),
    ('"teleport the arm to the back"', '{"action":"move_to","target":{"x":0.0,"y":0.15,"z":-0.15}}'),
    ('"add a bottle to the right"', '{"action":"spawn","object":"bottle","target":{"x":0.15,"y":0.25,"z":0.15}}'),
    ('"create apple at center"', '{"action":"spawn","object":"apple","target":{"x":0.0,"y":0.25,"z":0.25}}'),
    ('"spawn a bottle to the left of the apple"', '{"action":"spawn","object":"bottle","target":{"x":-0.15,"y":0.25,"z":0.15}}'),
    ('"grasp"', '{"action":"grasp"}'),
    ('"release"', '{"action":"release"}'),
    ('"do nothing"', '{"action":"none"}'),
    ('"spawn a bottle and move it to the right"', '[{"action":"spawn","object":"bottle","target":{"x":0.0,"y":0.25,"z":0.25}},{"action":"move_to","target":{"x":0.15,"y":0.25,"z":0.25}}]'),
    ('"grasp the bottle"', '[{"action":"move_to","target":{"x":0.0,"y":0.25,"z":0.25}},{"action":"grasp"}]'),
    ('"move to the apple, then to the bottle"', '[{"action":"move_to","target":{"x":0.0,"y":0.25,"z":0.25}},{"action":"move_to","target":{"x":0.15,"y":0.25,"z":0.15}}]'),
]

POSITION_KEYWORDS_FORMATTED = "\n".join(
    f'  "{kw}" → ({x:7.3f}, {y:.3f}, {z:.3f})'
    for kw, (x, y, z) in sorted(POSITION_KEYWORDS.items())
)

SYSTEM_PROMPT = f"""You are a robot arm controller.

ACTIONS:
  move_to  -> {{"action":"move_to","target":{{"x":float,"y":float,"z":float}}}}
  grasp    -> {{"action":"grasp"}}
  release  -> {{"action":"release"}}
  spawn    -> {{"action":"spawn","object":"name","target":{{"x":float,"y":float,"z":float}}}}
  none     -> {{"action":"none"}}

You can return a single action object, or a JSON array of action objects for multi-step commands.
Examples:
  "spawn a bottle and move it to the right" -> [{{"action":"spawn",...}},{{"action":"move_to",...}}]
  "grasp the bottle" -> [{{"action":"move_to",...}},{{"action":"grasp"}}]
  "add an apple" -> {{"action":"spawn",...}}

WORKSPACE (Three.js frame: x=right, y=up, z=toward viewer):
  x in [{WORKSPACE['x_min']}, {WORKSPACE['x_max']}], y in [{WORKSPACE['y_min']}, {WORKSPACE['y_max']}], z in [{WORKSPACE['z_min']}, {WORKSPACE['z_max']}]
  Center = {MIDDLE}

POSITION KEYWORDS (map to these coordinates):
{POSITION_KEYWORDS_FORMATTED}

POSITIONAL QUALIFIERS (common phrases mapped to keywords):
{chr(10).join(f'  "{p}" -> {k}' for p, k in POSITIONAL_QUALIFIERS.items())}
If the user uses an unfamiliar positional phrase, infer the intent and map to the closest keyword. Unknown directions default to center.

RULES:
- spawn: triggered by create/place/spawn/add/put/make/introduce + object name + optional position.
  If position is a keyword like "right" or "left", use the coordinates above.
  If position is "here" or unspecified, use the current Hand position.
- move_to: triggered by move/go/reach. Extract explicit x y z numbers if given,
  or use position keywords, or move to a named object.
- grasp: triggered by grab/pick/take/get.
- release: triggered by release/drop."""
