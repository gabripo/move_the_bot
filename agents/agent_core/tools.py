import re

from constants import (BUILTIN_OBJECTS, MIDDLE, POSITIONAL_QUALIFIERS,
                       POSITION_KEYWORDS)


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


def split_commands(voice):
    spawn_verbs = ["create", "spawn", "place", "make", "add", "put", "set", "introduce"]
    move_verbs = ["move", "go", "teleport", "position"]

    def prepend_verb(parts, first_part):
        verb = None
        ft = first_part.lower().strip()
        for kw in spawn_verbs + move_verbs:
            if ft.startswith(kw):
                verb = kw
                break
        if verb:
            for i in range(1, len(parts)):
                pt = parts[i].lower().strip()
                has_verb = any(pt.startswith(kw) for kw in spawn_verbs + move_verbs)
                if not has_verb:
                    parts[i] = f"{verb} {parts[i]}"
        return parts

    t = voice.strip()
    comma_parts = re.split(r",\s*", t)
    comma_parts = [p.strip() for p in comma_parts if p.strip()]
    result = []
    for part in comma_parts:
        and_parts = re.split(r"\s+and\s+", part, flags=re.IGNORECASE)
        and_parts = [p.strip() for p in and_parts if p.strip()]
        and_parts = prepend_verb(and_parts, and_parts[0])
        result.extend(and_parts)
    return result if result else [voice]
