"""Skill request validation: the gate every command passes before the robot moves."""
import pytest

from move_the_bot.skills import SKILLS, describe, validate


def test_valid_requests_are_cleaned():
    assert validate({"skill": "PICK", "object": " Apple "}) == {"skill": "pick", "object": "apple"}
    assert validate({"skill": "place"}) == {"skill": "place"}
    assert validate({"skill": "place", "at": {"position": "Middle"}}) == {
        "skill": "place", "at": {"position": "center"}}
    assert validate({"skill": "spawn", "object": "cube", "at": {"object": "Can", "relation": "left of"}}) == {
        "skill": "spawn", "object": "cube", "at": {"object": "can", "relation": "left_of"}}
    assert validate({"skill": "move_by", "dz": "0.05"}) == {"skill": "move_by", "dx": 0.0, "dy": 0.0, "dz": 0.05}
    assert validate({"skill": "gripper", "state": "closed"}) == {"skill": "gripper", "state": "close"}
    assert validate({"action": "home", "id": 7}) == {"skill": "home", "id": "7"}


@pytest.mark.parametrize("request_", [
    None, [], "pick", {}, {"skill": "fly"}, {"skill": "pick"}, {"skill": "pick", "object": ""},
    {"skill": "spawn", "object": "x" * 50},
    {"skill": "place", "at": "left"}, {"skill": "place", "at": {"position": "moon"}},
    {"skill": "place", "at": {"object": "cube", "relation": "inside"}},
    {"skill": "place", "at": {"x": 5, "y": 0}}, {"skill": "place", "at": {"x": "a", "y": 0}},
    {"skill": "move_to"}, {"skill": "move_to", "at": {}},
    {"skill": "move_by"}, {"skill": "move_by", "dx": 2}, {"skill": "gripper", "state": "half"},
])
def test_invalid_requests_are_rejected(request_):
    with pytest.raises(ValueError):
        validate(request_)


def test_every_skill_has_help_text():
    assert all(len(text) > 10 for text in SKILLS.values())


def test_describe():
    assert describe({"skill": "pick", "object": "apple"}) == "pick apple"
    assert describe({"skill": "place", "at": {"object": "cube", "relation": "on"}}) == "place on cube"
    assert describe({"skill": "spawn", "object": "mug", "at": {"position": "left"}}) == "spawn mug at left"
