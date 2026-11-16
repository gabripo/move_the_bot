"""The table-top world model."""
import math

import pytest

from move_the_bot.world import CATALOGUE, POSITIONS, World


def test_objects_rest_on_the_table():
    w = World()
    apple = w.add("apple", 0.2, 0.0)
    assert apple.z == pytest.approx(CATALOGUE["apple"]["size"][2] / 2)
    assert apple.name == "apple" and w.last == "apple"


def test_names_are_unique_and_colours_are_kept():
    w = World()
    assert w.add("cube", 0.2, 0.0).name == "cube"
    assert w.add("cube", 0.2, 0.1).name == "cube 2"
    red = w.add("red cube", 0.2, -0.1)
    assert red.name == "red cube" and red.color == "#e53935" and red.kind == "cube"
    assert w.add("orange", 0.3, 0.0).kind == "orange"          # the fruit, not the colour


def test_aliases_and_unknown_objects():
    w = World()
    assert w.add("box", 0.2, 0.0).kind == "cube"
    duck = w.add("rubber duck", 0.2, 0.1)
    assert duck.shape == "box" and duck.size == (0.05, 0.05, 0.05)


def test_find_resolves_references():
    w = World()
    w.add("can", 0.2, -0.1)
    w.add("red cube", 0.2, 0.0)
    w.add("blue cube", 0.2, 0.1)
    assert w.find("the can").name == "can"
    assert w.find("red cube").name == "red cube"
    assert w.find("cube").name == "blue cube"           # the most recent one
    assert w.find("it").name == "blue cube"
    assert w.find("box").kind == "cube"
    assert w.find("banana") is None and w.find("") is None


def test_stacking_and_what_is_on_top():
    w = World()
    cube = w.add("cube", 0.2, 0.0)
    apple = w.add("apple", 0.2, 0.0, on="cube")
    assert apple.z == pytest.approx(cube.top + apple.size[2] / 2)
    assert w.resting_on("cube") == ["apple"]
    assert w.resting_on("apple") == []


def test_attach_follow_and_drop():
    w = World()
    cube = w.add("cube", 0.2, 0.0)
    identity = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    w.attach("cube", identity, [0.2, 0.0, 0.05])
    assert w.held == "cube" and cube.held
    w.follow(identity, [0.3, 0.1, 0.20])
    assert (cube.x, cube.y) == pytest.approx((0.3, 0.1))
    assert cube.z == pytest.approx(0.20 - 0.05 + 0.02)
    dropped = w.detach()
    assert dropped is cube and w.held is None
    assert cube.z == pytest.approx(0.02)                # fell straight down onto the table


def test_held_object_rotates_with_the_gripper():
    w = World()
    cube = w.add("cube", 0.2, 0.0)
    identity = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    w.attach("cube", identity, [0.2, 0.0, 0.02])
    quarter_turn = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]   # 90 degrees about z
    w.follow(quarter_turn, [0.2, 0.0, 0.02])
    assert cube.quat == pytest.approx((0, 0, math.sqrt(0.5), math.sqrt(0.5)))


def test_drop_onto_another_object():
    w = World()
    can = w.add("can", 0.25, 0.0)
    cube = w.add("cube", 0.15, 0.0)
    identity = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    w.attach("cube", identity, [0.15, 0.0, 0.03])
    w.follow(identity, [0.25, 0.0, 0.2])
    w.detach()
    assert cube.z == pytest.approx(can.top + 0.02)


def test_places_are_resolved():
    w = World()
    cube = w.add("cube", 0.2, 0.0)
    assert w.resolve_place({"position": "left"}) == (*POSITIONS["left"], None)
    assert w.resolve_place({"position": "middle"})[:2] != (cube.x, cube.y)   # occupied: nudged
    assert w.resolve_place({"object": "cube", "relation": "on"}) == (cube.x, cube.y, "cube")
    x, y, on = w.resolve_place({"object": "cube", "relation": "left_of"})
    assert on is None and y > cube.y + 0.04 and x == pytest.approx(cube.x)
    assert w.resolve_place({"hand": True}, hand=(0.25, 0.1, 0.1))[:2] == pytest.approx((0.25, 0.1))
    with pytest.raises(ValueError):
        w.resolve_place({"hand": True})
    with pytest.raises(ValueError):
        w.resolve_place({"object": "banana", "relation": "on"})


def test_places_stay_within_reach():
    w = World()
    x, y, _ = w.resolve_place({"x": 0.9, "y": 0.0})
    assert x <= 0.0388 + 0.33 + 1e-9
    x, y, _ = w.resolve_place({"x": 0.0, "y": 0.0})
    assert x >= 0.09


def test_free_spot_avoids_other_objects():
    w = World()
    w.add("cube", 0.22, 0.0)
    x, y = w.free_spot(0.22, 0.0, 0.03)
    assert math.hypot(x - 0.22, y) >= 0.02 + 0.03 + 0.03 - 1e-9


def test_snapshot_round_trip():
    w = World()
    w.add("apple", 0.2, 0.0)
    w.add("red cube", 0.25, 0.1)
    copy = World.from_snapshot(w.snapshot())
    assert list(copy.objects) == ["apple", "red cube"]
    assert copy.find("cube").name == "red cube"


def test_remove_and_clear():
    w = World()
    w.add("apple", 0.2, 0.0)
    w.add("cube", 0.25, 0.1)
    w.remove("apple")
    assert list(w.objects) == ["cube"]
    w.clear()
    assert not w.objects and w.held is None and w.last is None
