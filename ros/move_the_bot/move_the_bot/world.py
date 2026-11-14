"""The table-top world: which objects exist, where they are, and what the gripper holds.

Pure Python (no ROS imports) so it can be unit-tested and reused.

All coordinates are in the robot's base frame, in metres:
x points forward (away from the base), y to the robot's left, z up. The table surface is z = 0.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# What can be created without downloading anything. `size` is (x, y, z) in metres.
CATALOGUE = {
    "apple": {"shape": "sphere", "size": (0.055, 0.055, 0.055), "color": "#c62828"},
    "orange": {"shape": "sphere", "size": (0.06, 0.06, 0.06), "color": "#ef6c00"},
    "ball": {"shape": "sphere", "size": (0.05, 0.05, 0.05), "color": "#1e88e5"},
    "cube": {"shape": "box", "size": (0.04, 0.04, 0.04), "color": "#e53935"},
    "can": {"shape": "cylinder", "size": (0.05, 0.05, 0.085), "color": "#b0bec5"},
    "mug": {"shape": "cylinder", "size": (0.06, 0.06, 0.07), "color": "#f5f5f5"},
    "bottle": {"shape": "cylinder", "size": (0.045, 0.045, 0.13), "color": "#26a69a"},
    "cylinder": {"shape": "cylinder", "size": (0.04, 0.04, 0.06), "color": "#8e24aa"},
}

ALIASES = {
    "box": "cube", "block": "cube", "brick": "cube", "dice": "cube",
    "sphere": "ball",
    "soda can": "can", "tin": "can", "coke": "can", "soda": "can",
    "cup": "mug", "coffee mug": "mug", "coffee cup": "mug", "coffee": "mug",
    "water bottle": "bottle", "flask": "bottle",
    "tube": "cylinder",
}

COLORS = {
    "red": "#e53935", "green": "#43a047", "blue": "#1e88e5", "yellow": "#fdd835",
    "orange": "#fb8c00", "purple": "#8e24aa", "pink": "#ec407a", "white": "#fafafa",
    "black": "#263238", "grey": "#90a4ae", "gray": "#90a4ae", "brown": "#6d4c41",
}

# Named places on the table: (x, y).
POSITIONS = {
    "center": (0.22, 0.0),
    "left": (0.20, 0.13),
    "right": (0.20, -0.13),
    "front": (0.30, 0.0),
    "back": (0.15, 0.0),
    "front left": (0.27, 0.11),
    "front right": (0.27, -0.11),
    "back left": (0.14, 0.13),
    "back right": (0.14, -0.13),
}
POSITION_ALIASES = {
    "middle": "center", "centre": "center",
    "far": "front", "forward": "front", "ahead": "front",
    "near": "back", "close": "back", "rear": "back",
}

RELATIONS = ("on", "left_of", "right_of", "in_front_of", "behind", "next_to", "above")

# Where the arm can comfortably reach on the table, measured from the shoulder axis.
SHOULDER_X = 0.0388
REACH_MIN, REACH_MAX = 0.10, 0.33
TABLE_Y_MAX = 0.26
MAX_GRASP_WIDTH = 0.075   # widest object the gripper can close on
UNKNOWN_SIZE = (0.05, 0.05, 0.05)
GAP = 0.03                # free space kept between neighbouring objects


def canonical_kind(word: str) -> str:
    """'box' -> 'cube', 'soda can' -> 'can'; unknown words are returned unchanged."""
    w = " ".join(word.lower().split())
    return ALIASES.get(w, w)


def canonical_position(word: str) -> str | None:
    w = " ".join(word.lower().replace("-", " ").split())
    w = POSITION_ALIASES.get(w, w)
    return w if w in POSITIONS else None


@dataclass
class Obj:
    name: str
    kind: str
    shape: str
    size: tuple
    color: str
    x: float
    y: float
    z: float                       # centre of the object
    model: str = ""                # web path of a 3D model ("" = draw the basic shape)
    quat: tuple = (0.0, 0.0, 0.0, 1.0)
    held: bool = False

    @property
    def radius(self) -> float:
        return 0.5 * max(self.size[0], self.size[1])

    @property
    def top(self) -> float:
        return self.z + 0.5 * self.size[2]

    @property
    def width(self) -> float:
        """Width the gripper has to close to."""
        return min(self.size[0], self.size[1])

    def grasp_point(self) -> tuple:
        """Where the fingertips should be: the middle, or 3 cm below the top for tall objects."""
        z = max(self.z, self.top - 0.03)
        return (self.x, self.y, z)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "kind": self.kind, "shape": self.shape,
            "size": [round(v, 4) for v in self.size], "color": self.color, "model": self.model,
            "position": [round(self.x, 4), round(self.y, 4), round(self.z, 4)],
            "quaternion": [round(v, 5) for v in self.quat],
            "held": self.held,
        }


@dataclass
class World:
    objects: dict = field(default_factory=dict)
    held: str | None = None
    last: str | None = None        # the object "it" refers to
    _grip: tuple | None = None     # held object pose in the gripper frame (rotation 3x3, offset)

    # ----------------------------------------------------------------- lookup

    def find(self, reference: str | None) -> Obj | None:
        """Resolve 'apple', 'the red cube', 'cube 2', 'it'... to an object, or None."""
        if not reference:
            return None
        ref = " ".join(reference.lower().split())
        ref = re.sub(r"^(the|a|an|this|that|my|another)\s+", "", ref)
        if ref in ("it", "them", "that", "this", "one", "object", "thing"):
            return self.objects.get(self.last) if self.last else (
                self.objects[self.held] if self.held else None)
        if ref in self.objects:
            return self.objects[ref]
        words = ref.split()
        color = words[0] if len(words) > 1 and words[0] in COLORS else None
        kind = canonical_kind(" ".join(words[1:]) if color else ref)
        matches = [o for o in self.objects.values()
                   if o.kind == kind and (color is None or o.name.startswith(color + " "))]
        if not matches and not color:
            matches = [o for o in self.objects.values() if kind in o.name.split()]
        if not matches:
            return None
        if self.last and any(o.name == self.last for o in matches):
            return self.objects[self.last]
        return matches[-1]

    def nearest(self, point, max_distance: float) -> Obj | None:
        best, best_d = None, max_distance
        for o in self.objects.values():
            if o.held:
                continue
            d = math.dist(point, o.grasp_point())
            if d < best_d:
                best, best_d = o, d
        return best

    # ------------------------------------------------------------- placement

    @staticmethod
    def clamp_to_reach(x: float, y: float) -> tuple:
        """Pull a point back onto the part of the table the arm can reach."""
        y = max(-TABLE_Y_MAX, min(TABLE_Y_MAX, y))
        dx, dy = x - SHOULDER_X, y
        r = math.hypot(dx, dy)
        if r < 1e-6:
            return (SHOULDER_X + REACH_MIN, 0.0)
        scale = max(REACH_MIN, min(REACH_MAX, r)) / r
        x = SHOULDER_X + dx * scale
        y = dy * scale
        return (max(x, 0.09), y)   # never behind the base

    def support(self, x: float, y: float, ignore: str | None = None) -> tuple:
        """Height of the surface under (x, y) and the object providing it (None = the table)."""
        top, under = 0.0, None
        for o in self.objects.values():
            if o.held or o.name == ignore:
                continue
            if math.hypot(o.x - x, o.y - y) <= o.radius and o.top > top:
                top, under = o.top, o
        return top, under

    def resting_on(self, name: str) -> list:
        """Names of the objects lying on top of `name`."""
        below = self.objects.get(name)
        if below is None:
            return []
        return [o.name for o in self.objects.values()
                if o is not below and not o.held
                and math.hypot(o.x - below.x, o.y - below.y) <= below.radius
                and abs((o.z - 0.5 * o.size[2]) - below.top) < 0.01]

    def is_free(self, x: float, y: float, radius: float, ignore: str | None = None) -> bool:
        for o in self.objects.values():
            if o.held or o.name == ignore:
                continue
            if math.hypot(o.x - x, o.y - y) < o.radius + radius + GAP:
                return False
        return True

    def free_spot(self, x: float, y: float, radius: float, ignore: str | None = None) -> tuple:
        """The reachable free spot closest to (x, y)."""
        x, y = self.clamp_to_reach(x, y)
        if self.is_free(x, y, radius, ignore):
            return (x, y)
        for ring in range(1, 12):
            r = ring * 0.02
            for k in range(8 * ring):
                a = 2 * math.pi * k / (8 * ring)
                cx, cy = x + r * math.cos(a), y + r * math.sin(a)
                if self.clamp_to_reach(cx, cy) != (cx, cy):
                    continue
                if self.is_free(cx, cy, radius, ignore):
                    return (cx, cy)
        return (x, y)

    def resolve_place(self, place: dict | None, radius: float = 0.03, hand=None,
                      ignore: str | None = None, default=None) -> tuple:
        """Turn a symbolic place into (x, y, on_object_name_or_None).

        `place` is one of
          {"x": .., "y": ..}                        explicit coordinates
          {"position": "left"}                      a named spot on the table
          {"object": "cube", "relation": "on"}      relative to another object
          {"hand": true}                            where the user's hand points (teleoperation)
        Raises ValueError with a readable message when it cannot be resolved.
        """
        place = place or {}
        if "x" in place and "y" in place:
            x, y = self.clamp_to_reach(float(place["x"]), float(place["y"]))
            return (x, y, None)
        if place.get("hand"):
            if hand is None:
                raise ValueError("I do not see your hand: turn on hand control first")
            return (*self.free_spot(hand[0], hand[1], radius, ignore), None)
        if "object" in place:
            ref = self.find(place["object"])
            if ref is None:
                raise ValueError(f"there is no {place['object']} on the table")
            relation = place.get("relation", "next_to")
            if relation in ("on", "above"):
                return (ref.x, ref.y, ref.name)
            step = ref.radius + radius + GAP + 0.01
            dx, dy = {
                "left_of": (0.0, step), "right_of": (0.0, -step),
                "in_front_of": (step, 0.0), "behind": (-step, 0.0),
            }.get(relation, (0.0, step if ref.y <= 0 else -step))
            return (*self.free_spot(ref.x + dx, ref.y + dy, radius, ignore), None)
        if "position" in place:
            name = canonical_position(str(place["position"]))
            if name is None:
                raise ValueError(f"I do not know the place '{place['position']}'")
            return (*self.free_spot(*POSITIONS[name], radius, ignore), None)
        if default is not None:
            return (*self.free_spot(default[0], default[1], radius, ignore), None)
        return (*self.free_spot(*POSITIONS["center"], radius, ignore), None)

    # --------------------------------------------------------------- changes

    def unique_name(self, base: str) -> str:
        if base not in self.objects:
            return base
        n = 2
        while f"{base} {n}" in self.objects:
            n += 1
        return f"{base} {n}"

    def add(self, description: str, x: float, y: float, on: str | None = None,
            model: str = "", size=None) -> Obj:
        """Create an object such as 'apple' or 'red cube' at (x, y), resting on what is below."""
        words = " ".join(description.lower().split()).split()
        color = COLORS[words[0]] if len(words) > 1 and words[0] in COLORS else None
        kind = canonical_kind(" ".join(words[1:]) if color else " ".join(words))
        spec = CATALOGUE.get(kind)
        shape = spec["shape"] if spec else "box"
        dims = tuple(size) if size else (spec["size"] if spec else UNKNOWN_SIZE)
        name = self.unique_name(f"{words[0]} {kind}" if color else kind)
        if on and on in self.objects:
            x, y = self.objects[on].x, self.objects[on].y
        base, _ = self.support(x, y)
        obj = Obj(name=name, kind=kind, shape=shape, size=dims,
                  color=color or (spec["color"] if spec else "#78909c"),
                  x=x, y=y, z=base + 0.5 * dims[2], model=model)
        self.objects[name] = obj
        self.last = name
        return obj

    def remove(self, name: str) -> None:
        if name in self.objects:
            if self.held == name:
                self.held, self._grip = None, None
            del self.objects[name]
            if self.last == name:
                self.last = None

    def clear(self) -> None:
        self.objects.clear()
        self.held = self.last = self._grip = None

    # ------------------------------------------------------- grasp / release

    def attach(self, name: str, tool_rotation, tool_position) -> None:
        """Remember how the object sits in the gripper so it can follow it."""
        obj = self.objects[name]
        offset = [obj.x - tool_position[0], obj.y - tool_position[1], obj.z - tool_position[2]]
        # Express the offset in the gripper frame: R^T * offset.
        local = tuple(sum(tool_rotation[r][c] * offset[r] for r in range(3)) for c in range(3))
        self._grip = (tuple(tuple(row) for row in tool_rotation), local)
        obj.held = True
        self.held = name
        self.last = name

    def follow(self, tool_rotation, tool_position) -> Obj | None:
        """Move the held object with the gripper. Returns it, or None when nothing is held."""
        if not self.held or self._grip is None:
            return None
        obj = self.objects[self.held]
        grasp_rotation, local = self._grip
        world = [sum(tool_rotation[r][c] * local[c] for c in range(3)) for r in range(3)]
        obj.x, obj.y, obj.z = (tool_position[i] + world[i] for i in range(3))
        # Orientation relative to the moment of the grasp: R_now * R_grasp^T.
        rel = [[sum(tool_rotation[r][k] * grasp_rotation[c][k] for k in range(3))
                for c in range(3)] for r in range(3)]
        obj.quat = _quaternion(rel)
        return obj

    def detach(self) -> Obj | None:
        """Let go: the object drops straight down onto whatever is below it, upright."""
        if not self.held:
            return None
        obj = self.objects[self.held]
        obj.held = False
        self.held, self._grip = None, None
        base, _ = self.support(obj.x, obj.y, ignore=obj.name)
        obj.z = base + 0.5 * obj.size[2]
        obj.quat = (0.0, 0.0, 0.0, 1.0)
        return obj

    def snapshot(self) -> list:
        return [o.to_dict() for o in self.objects.values()]

    @classmethod
    def from_snapshot(cls, items: list) -> "World":
        """Rebuild a world from `snapshot()` output (used by the agent, which only listens)."""
        world = cls()
        for d in items:
            x, y, z = d["position"]
            world.objects[d["name"]] = Obj(
                name=d["name"], kind=d.get("kind", d["name"]), shape=d.get("shape", "box"),
                size=tuple(d.get("size", UNKNOWN_SIZE)), color=d.get("color", "#78909c"),
                x=x, y=y, z=z, model=d.get("model", ""), held=bool(d.get("held")))
            if d.get("held"):
                world.held = d["name"]
        return world


def _quaternion(m) -> tuple:
    """Rotation matrix (3x3 nested lists) -> quaternion (x, y, z, w)."""
    trace = m[0][0] + m[1][1] + m[2][2]
    if trace > 0:
        s = 2.0 * math.sqrt(trace + 1.0)
        return ((m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s, 0.25 * s)
    if m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = 2.0 * math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2])
        return (0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s, (m[2][1] - m[1][2]) / s)
    if m[1][1] > m[2][2]:
        s = 2.0 * math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2])
        return ((m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s, (m[0][2] - m[2][0]) / s)
    s = 2.0 * math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1])
    return ((m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s, (m[1][0] - m[0][1]) / s)
