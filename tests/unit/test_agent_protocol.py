import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest


def parse_action(json_str):
    parsed = json.loads(json_str)
    action = parsed.get("action")
    if action not in ("move_to", "grasp", "release", "spawn", "stop", "none"):
        raise ValueError(f"Unknown action: {action}")
    if action == "move_to":
        target = parsed["target"]
        for key in ("x", "y", "z"):
            if key not in target:
                raise ValueError(f"Missing target.{key}")
            val = float(target[key])
            if not (-0.5 <= val <= 0.5):
                raise ValueError(f"Out of bounds: {key}={val}")
    if action == "spawn":
        if "object" not in parsed:
            raise ValueError("Missing object name for spawn")
        target = parsed.get("target", {})
        for key in ("x", "y", "z"):
            if key not in target:
                raise ValueError(f"Missing target.{key}")
    return parsed


def test_valid_move_to():
    action = parse_action('{"action":"move_to","target":{"x":0.1,"y":0.2,"z":0.3}}')
    assert action["action"] == "move_to"
    assert action["target"]["x"] == 0.1


def test_valid_grasp():
    action = parse_action('{"action":"grasp"}')
    assert action["action"] == "grasp"


def test_valid_release():
    action = parse_action('{"action":"release"}')
    assert action["action"] == "release"


def test_valid_spawn():
    action = parse_action(
        '{"action":"spawn","object":"apple","target":{"x":0.2,"y":0.0,"z":0.05}}'
    )
    assert action["action"] == "spawn"
    assert action["object"] == "apple"


def test_valid_stop():
    action = parse_action('{"action":"stop"}')
    assert action["action"] == "stop"


def test_valid_none():
    action = parse_action('{"action":"none"}')
    assert action["action"] == "none"


def test_invalid_json():
    with pytest.raises(json.JSONDecodeError):
        parse_action("not json")


def test_unknown_action():
    with pytest.raises(ValueError, match="Unknown action"):
        parse_action('{"action":"fly"}')


def test_missing_target():
    with pytest.raises(KeyError):
        parse_action('{"action":"move_to"}')


def test_out_of_bounds():
    with pytest.raises(ValueError, match="Out of bounds"):
        parse_action('{"action":"move_to","target":{"x":2.0,"y":0.0,"z":0.0}}')


def test_missing_object_for_spawn():
    with pytest.raises(ValueError, match="Missing object"):
        parse_action('{"action":"spawn","target":{"x":0.2,"y":0.0,"z":0.05}}')


def test_missing_action_field():
    with pytest.raises(ValueError, match="Unknown action"):
        parse_action('{"x":1}')
