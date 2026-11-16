"""The rule parser: everyday sentences in, skill requests out."""
import pytest

from move_the_bot.language import parse, split_clauses
from move_the_bot.skills import validate
from move_the_bot.world import World


def world_with(*names):
    w = World()
    for i, name in enumerate(names):
        w.add(name, 0.2, -0.1 + 0.1 * i)
    return w


def skills(text, world=None):
    result = parse(text, world)
    assert result is not None, f"not understood: {text!r}"
    for s in result:
        validate(s)          # everything the parser emits must be a valid request
    return result


def names(result):
    return [s["skill"] for s in result]


# ------------------------------------------------------------------ creating

@pytest.mark.parametrize("text", [
    "create an apple", "spawn an apple", "add an apple", "make an apple", "give me an apple",
    "Please create an apple.", "can you create an apple?", "I want an apple",
])
def test_create_variants(text):
    assert skills(text) == [{"skill": "spawn", "object": "apple"}]


def test_create_with_colour_and_position():
    assert skills("create a red cube on the left") == [
        {"skill": "spawn", "object": "red cube", "at": {"position": "left"}}]
    assert skills("add a blue ball in the middle")[0]["at"] == {"position": "center"}
    assert skills("spawn a mug at the front right")[0]["at"] == {"position": "front right"}


def test_create_several():
    assert skills("create an apple and a mug") == [
        {"skill": "spawn", "object": "apple"}, {"skill": "spawn", "object": "mug"}]
    assert names(skills("create three cubes")) == ["spawn"] * 3
    assert names(skills("create two red cubes and a can")) == ["spawn", "spawn", "spawn"]


def test_create_relative_to_another_object():
    w = world_with("apple")
    assert skills("create a bottle to the left of the apple", w) == [
        {"skill": "spawn", "object": "bottle", "at": {"object": "apple", "relation": "left_of"}}]
    assert skills("put a cube on the can", world_with("can")) == [
        {"skill": "spawn", "object": "cube", "at": {"object": "can", "relation": "on"}}]
    assert skills("add a ball next to the mug", world_with("mug"))[0]["at"] == {
        "object": "mug", "relation": "next_to"}


def test_create_aliases_and_plural():
    assert skills("create a box")[0]["object"] == "cube"
    assert skills("add a soda can")[0]["object"] == "can"
    assert names(skills("add 2 boxes")) == ["spawn", "spawn"]


def test_create_unknown_object_is_passed_on():
    assert skills("create a banana") == [{"skill": "spawn", "object": "banana"}]
    assert skills("spawn a rubber duck on the left") == [
        {"skill": "spawn", "object": "rubber duck", "at": {"position": "left"}}]


def test_create_at_coordinates_and_hand():
    assert skills("create an apple at 0.25 0.1")[0]["at"] == {"x": 0.25, "y": 0.1}
    assert skills("create a cube here")[0]["at"] == {"hand": True}


# ------------------------------------------------------------------- picking

@pytest.mark.parametrize("text", [
    "grab the apple", "pick up the apple", "pick the apple", "grasp the apple", "take the apple",
    "get the apple", "could you grab the apple", "lift the apple",
])
def test_pick_variants(text):
    assert skills(text, world_with("apple")) == [{"skill": "pick", "object": "apple"}]


def test_pick_the_named_object_not_another_one():
    # Old bug: with a cube and a can on the table, "grab the cube" could resolve to the can.
    w = world_with("can", "cube", "apple")
    assert skills("grab the cube", w) == [{"skill": "pick", "object": "cube"}]
    assert skills("grab the red cube", world_with("red cube", "blue cube")) == [
        {"skill": "pick", "object": "red cube"}]
    assert skills("pick cube 2", world_with("cube", "cube")) == [{"skill": "pick", "object": "cube 2"}]


def test_pick_it():
    w = world_with("apple")
    assert skills("grab it", w) == [{"skill": "pick", "object": "apple"}]
    assert skills("create a mug and grab it") == [
        {"skill": "spawn", "object": "mug"}, {"skill": "pick", "object": "mug"}]


def test_pick_something_unknown_is_not_silently_replaced():
    # "grab the banana" with an apple on the table must not grab the apple.
    assert skills("grab the banana", world_with("apple")) == [{"skill": "pick", "object": "banana"}]
    assert skills("pick up the rubber duck") == [{"skill": "pick", "object": "rubber duck"}]


def test_grab_with_nothing_on_the_table_closes_the_gripper():
    assert skills("grab") == [{"skill": "gripper", "state": "close"}]


# ------------------------------------------------------------------- placing

def test_put_down_does_not_create_a_second_object():
    # Old bug: "put the apple down" spawned another apple.
    w = world_with("apple")
    w.held = "apple"
    assert skills("put the apple down", w) == [{"skill": "place"}]
    assert skills("put it down", w) == [{"skill": "place"}]
    assert skills("drop it", w) == [{"skill": "place"}]
    assert skills("release", w) == [{"skill": "place"}]


def test_release_with_empty_gripper_opens_it():
    assert skills("release") == [{"skill": "gripper", "state": "open"}]
    assert skills("let go") == [{"skill": "gripper", "state": "open"}]


def test_move_an_object_is_pick_and_place():
    w = world_with("apple", "cube")
    assert skills("put the apple on the cube", w) == [
        {"skill": "pick", "object": "apple"},
        {"skill": "place", "at": {"object": "cube", "relation": "on"}}]
    assert skills("move the apple to the left", w) == [
        {"skill": "pick", "object": "apple"}, {"skill": "place", "at": {"position": "left"}}]
    assert skills("stack the cube on the apple", w)[1]["at"] == {"object": "apple", "relation": "on"}
    assert skills("bring the cube to the front", w)[1]["at"] == {"position": "front"}


def test_pick_then_place_in_one_sentence():
    w = world_with("apple", "mug")
    assert skills("pick up the apple and put it next to the mug", w) == [
        {"skill": "pick", "object": "apple"},
        {"skill": "place", "at": {"object": "mug", "relation": "next_to"}}]
    assert skills("grab the apple, then put it on the right", w) == [
        {"skill": "pick", "object": "apple"}, {"skill": "place", "at": {"position": "right"}}]
    assert skills("take the apple to the left", w) == [
        {"skill": "pick", "object": "apple"}, {"skill": "place", "at": {"position": "left"}}]


def test_put_held_object_somewhere():
    w = world_with("apple", "cube")
    w.held = "apple"
    assert skills("put it on the cube", w) == [
        {"skill": "place", "at": {"object": "cube", "relation": "on"}}]
    assert skills("place it on the left", w) == [{"skill": "place", "at": {"position": "left"}}]


def test_full_demo_sentence():
    assert skills("create an apple and a red cube, then put the apple on the cube") == [
        {"skill": "spawn", "object": "apple"},
        {"skill": "spawn", "object": "red cube"},
        {"skill": "pick", "object": "apple"},
        {"skill": "place", "at": {"object": "cube", "relation": "on"}}]


# ---------------------------------------------------------------- arm motion

def test_can_you_is_not_the_object_can():
    # Old bug: "can you move left" matched the object "can".
    w = world_with("can")
    result = skills("can you move left", w)
    assert names(result) == ["move_by"]
    assert result[0]["dy"] == pytest.approx(0.05)


@pytest.mark.parametrize("text,axis,value", [
    ("move left", "dy", 0.05), ("move right", "dy", -0.05), ("go up", "dz", 0.05),
    ("move down", "dz", -0.05), ("move forward", "dx", 0.05), ("move back", "dx", -0.05),
    ("move up 10 cm", "dz", 0.10), ("move left 3 cm", "dy", 0.03), ("a bit higher", "dz", 0.02),
    ("move 8 cm to the right", "dy", -0.08), ("go down a little", "dz", -0.02),
    ("up", "dz", 0.05), ("lower", "dz", -0.05), ("move the arm up", "dz", 0.05),
])
def test_relative_moves(text, axis, value):
    result = skills(text)
    assert names(result) == ["move_by"]
    assert result[0][axis] == pytest.approx(value)


def test_move_to_places_and_objects():
    assert skills("move to the left") == [{"skill": "move_to", "at": {"position": "left"}}]
    assert skills("go to the center") == [{"skill": "move_to", "at": {"position": "center"}}]
    assert skills("move to the apple", world_with("apple")) == [
        {"skill": "move_to", "at": {"object": "apple", "relation": "above"}}]
    assert skills("move to the apple then to the mug", world_with("apple", "mug")) == [
        {"skill": "move_to", "at": {"object": "apple", "relation": "above"}},
        {"skill": "move_to", "at": {"object": "mug", "relation": "above"}}]
    assert skills("move to 0.2 0.1 0.15") == [
        {"skill": "move_to", "at": {"x": 0.2, "y": 0.1, "z": 0.15}}]


# -------------------------------------------------------------------- others

@pytest.mark.parametrize("text,expected", [
    ("go home", [{"skill": "home"}]), ("home", [{"skill": "home"}]),
    ("return to the home position", [{"skill": "home"}]),
    ("open the gripper", [{"skill": "gripper", "state": "open"}]),
    ("close your hand", [{"skill": "gripper", "state": "close"}]),
    ("stop", [{"skill": "stop"}]), ("stop!", [{"skill": "stop"}]),
    ("reset", [{"skill": "reset"}]), ("clear the table", [{"skill": "reset"}]),
    ("remove everything", [{"skill": "reset"}]),
])
def test_fixed_commands(text, expected):
    assert skills(text) == expected


def test_remove():
    w = world_with("apple", "mug")
    assert skills("remove the apple", w) == [{"skill": "remove", "object": "apple"}]
    assert skills("delete the apple and the mug", w) == [
        {"skill": "remove", "object": "apple"}, {"skill": "remove", "object": "mug"}]


@pytest.mark.parametrize("text", [
    "", "what is the weather like", "tell me a joke", "sort the objects by colour",
    "build a tower with everything", "how are you",
])
def test_unknown_commands_are_left_to_the_llm(text):
    assert parse(text, world_with("apple", "cube")) is None


def test_split_clauses():
    assert split_clauses("Create an apple, then grab it and put it left.") == [
        "create an apple", "grab it", "put it left"]
    assert split_clauses("move to 0.2, 0.1, 0.15") != []
