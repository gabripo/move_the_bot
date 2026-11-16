"""The skills the robot offers, and a validator for requests.

A skill request is a small JSON object, for example

    {"skill": "pick", "object": "apple"}
    {"skill": "place", "at": {"object": "cube", "relation": "on"}}

Every front-end produces the same requests: the rule parser, the LLM, the OpenClaw plugin, or
a script. The skill server (skill_server.py) executes them. See docs/skills.md.
"""
from __future__ import annotations

from .world import RELATIONS, canonical_position

SKILLS = {
    "spawn": "Create an object on the table. Fields: object (e.g. 'apple', 'red cube'), at (optional place).",
    "pick": "Move to an object and grasp it. Fields: object.",
    "place": "Put the held object down. Fields: at (optional place; default: straight below).",
    "move_to": "Move the gripper to a place without grasping. Fields: at (place), height (optional, metres above it).",
    "move_by": "Move the gripper relative to where it is. Fields: dx, dy, dz in metres (x forward, y left, z up).",
    "gripper": "Open or close the gripper. Fields: state ('open' or 'close').",
    "home": "Return the arm to its home pose.",
    "remove": "Delete an object. Fields: object.",
    "reset": "Remove all objects, open the gripper and go home.",
    "stop": "Stop the current motion and drop everything that is queued.",
}

PLACE_HELP = (
    'A place is ONE of: {"position": "left"} (center, left, right, front, back, front left, '
    'front right, back left, back right); {"object": "cube", "relation": "on"} (relations: '
    + ", ".join(RELATIONS)
    + '); {"x": 0.2, "y": 0.1} in metres (x forward 0.10..0.35, y left -0.25..0.25); '
    '{"hand": true} for where the user\'s hand points.'
)


def _number(value, name: str, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"'{name}' must be a number") from None
    if not low <= number <= high:
        raise ValueError(f"'{name}' must be between {low} and {high}")
    return number


def _place(place) -> dict:
    if not isinstance(place, dict):
        raise ValueError("'at' must be an object such as {\"position\": \"left\"}")
    if "x" in place or "y" in place:
        out = {"x": _number(place.get("x"), "x", -0.5, 0.6), "y": _number(place.get("y"), "y", -0.5, 0.5)}
        if place.get("z") is not None:
            out["z"] = _number(place["z"], "z", 0.0, 0.45)
        return out
    if place.get("hand"):
        return {"hand": True}
    if "object" in place:
        relation = str(place.get("relation", "next_to")).lower().replace(" ", "_")
        if relation not in RELATIONS:
            raise ValueError(f"unknown relation '{relation}'")
        return {"object": str(place["object"]).strip().lower(), "relation": relation}
    if "position" in place:
        name = canonical_position(str(place["position"]))
        if name is None:
            raise ValueError(f"unknown position '{place['position']}'")
        return {"position": name}
    raise ValueError("'at' needs a position, an object, coordinates or the hand")


def validate(request) -> dict:
    """Return a cleaned copy of a skill request, or raise ValueError saying what is wrong."""
    if not isinstance(request, dict):
        raise ValueError("a skill request must be a JSON object")
    skill = str(request.get("skill") or request.get("action") or "").strip().lower()
    if skill not in SKILLS:
        raise ValueError(f"unknown skill '{skill}'")
    out = {"skill": skill}
    if request.get("id") is not None:
        out["id"] = str(request["id"])
    if skill in ("spawn", "pick", "remove"):
        name = str(request.get("object") or "").strip().lower()
        if not name:
            raise ValueError(f"'{skill}' needs an object")
        if len(name) > 40:
            raise ValueError("object name is too long")
        out["object"] = name
    if skill in ("spawn", "place") and request.get("at") is not None:
        out["at"] = _place(request["at"])
    if skill == "move_to":
        out["at"] = _place(request.get("at"))
        if request.get("height") is not None:
            out["height"] = _number(request["height"], "height", 0.0, 0.3)
    if skill == "move_by":
        for axis in ("dx", "dy", "dz"):
            out[axis] = _number(request.get(axis, 0.0), axis, -0.3, 0.3)
        if not any(out[a] for a in ("dx", "dy", "dz")):
            raise ValueError("'move_by' needs a non-zero dx, dy or dz")
    if skill == "gripper":
        state = str(request.get("state", "")).lower()
        state = {"closed": "close", "opened": "open", "grasp": "close", "release": "open"}.get(state, state)
        if state not in ("open", "close"):
            raise ValueError("'gripper' needs state 'open' or 'close'")
        out["state"] = state
    return out


def describe(request: dict) -> str:
    """A short human-readable line for logs: 'pick apple', 'place on cube'."""
    skill = request.get("skill", "?")
    parts = [skill]
    if "object" in request:
        parts.append(request["object"])
    at = request.get("at")
    if at:
        if "position" in at:
            parts.append(f"at {at['position']}")
        elif "object" in at:
            parts.append(f"{at['relation'].replace('_', ' ')} {at['object']}")
        elif "hand" in at:
            parts.append("at the hand")
        else:
            parts.append(f"at ({at['x']:.2f}, {at['y']:.2f})")
    if skill == "move_by":
        parts.append(f"({request['dx']:+.2f}, {request['dy']:+.2f}, {request['dz']:+.2f})")
    if skill == "gripper":
        parts.append(request["state"])
    return " ".join(parts)
