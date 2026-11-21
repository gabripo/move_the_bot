"""The LLM fallback: prompts, parsing of model answers, and both back-ends (mocked network)."""
import json

import pytest
import requests

from move_the_bot import llm
from move_the_bot.world import World


def test_extract_json_tolerates_chatter():
    assert llm.extract_json('{"skills": []}') == {"skills": []}
    assert llm.extract_json('Sure! ```json\n{"skills": [{"skill": "home"}]}\n``` done') == {
        "skills": [{"skill": "home"}]}
    assert llm.extract_json('text {"a": "brace } in string"} more') == {"a": "brace } in string"}
    assert llm.extract_json('[{"skill": "home"}]') == [{"skill": "home"}]
    with pytest.raises(llm.LLMError):
        llm.extract_json("I cannot do that")


def test_interpret_keeps_valid_skills_and_reports_the_rest():
    answer = json.dumps({"skills": [
        {"skill": "pick", "object": "apple"},
        {"skill": "teleport", "object": "apple"},
        {"skill": "place", "at": {"position": "left"}},
    ], "say": "Moving the apple."})
    skills, say, problems = llm.interpret(answer)
    assert [s["skill"] for s in skills] == ["pick", "place"]
    assert say == "Moving the apple."
    assert len(problems) == 1 and "teleport" in problems[0]


def test_interpret_accepts_other_shapes():
    assert llm.interpret('{"skill": "home"}')[0] == [{"skill": "home"}]
    assert llm.interpret('[{"action": "home"}]')[0] == [{"skill": "home"}]
    assert llm.interpret('{"skills": [], "say": "I cannot juggle."}') == ([], "I cannot juggle.", [])


def test_interpret_limits_the_number_of_steps():
    answer = json.dumps({"skills": [{"skill": "home"}] * 50})
    assert len(llm.interpret(answer)[0]) == llm.MAX_SKILLS


def test_prompts_describe_the_scene():
    w = World()
    w.add("apple", 0.2, 0.0)
    w.add("red cube", 0.25, 0.1)
    prompt = llm.user_prompt("tidy up", w, hand=(0.2, 0.1, 0.1))
    assert "apple at x=0.20" in prompt and "red cube" in prompt and "hand points" in prompt
    assert "Table: empty" in llm.user_prompt("hi", World())
    system = llm.system_prompt()
    for skill in ("spawn", "pick", "place", "move_to", "gripper"):
        assert skill in system


class _Response:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


def test_ollama_backend(monkeypatch):
    calls = {}

    def post(url, json=None, timeout=None, **_):
        calls["url"], calls["body"] = url, json
        return _Response({"message": {"content": '{"skills": [{"skill": "home"}]}'}})

    monkeypatch.setattr(llm, "BACKEND", "ollama")
    monkeypatch.setattr(llm.requests, "post", post)
    skills, _, _ = llm.ask("go back", World())
    assert skills == [{"skill": "home"}]
    assert calls["url"].endswith("/api/chat") and calls["body"]["format"] == "json"
    assert calls["body"]["messages"][0]["role"] == "system"


def test_openai_compatible_backend(monkeypatch):
    calls = {}

    def post(url, json=None, headers=None, timeout=None, **_):
        calls["url"], calls["headers"], calls["body"] = url, headers, json
        return _Response({"choices": [{"message": {"content": '{"skills": [{"skill": "home"}]}'}}]})

    monkeypatch.setattr(llm, "BACKEND", "openai")
    monkeypatch.setattr(llm, "OPENAI_API_KEY", "nvapi-test")
    monkeypatch.setattr(llm.requests, "post", post)
    skills, _, _ = llm.ask("go back", World())
    assert skills == [{"skill": "home"}]
    assert calls["url"].endswith("/chat/completions")
    assert calls["headers"]["Authorization"] == "Bearer nvapi-test"


def test_network_problems_become_readable_errors(monkeypatch):
    def boom(*_a, **_k):
        raise requests.ConnectionError()

    monkeypatch.setattr(llm, "BACKEND", "ollama")
    monkeypatch.setattr(llm.requests, "post", boom)
    with pytest.raises(llm.LLMError, match="cannot reach the model"):
        llm.ask("hello", World())

    def slow(*_a, **_k):
        raise requests.Timeout()

    monkeypatch.setattr(llm.requests, "post", slow)
    with pytest.raises(llm.LLMError, match="did not answer"):
        llm.ask("hello", World())

    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: _Response({}, 500))
    with pytest.raises(llm.LLMError):
        llm.ask("hello", World())


def test_thirst_prefers_the_scanned_drink():
    world = World()
    world.add("mug", 0.2, 0.1)
    world.add("monster drink", 0.2, -0.1, size=(0.066, 0.066, 0.17))
    world.add("apple", 0.25, 0.0)
    assert llm.is_drink("monster drink") and llm.is_drink("mug 2") and not llm.is_drink("apple")
    assert [n for n, _ in llm.drinks(world, ["monster drink"])] == ["monster drink", "mug"]
    assert [n for n, _ in llm.drinks(world)] == ["mug", "monster drink"]         # not scanned: table order
    text = llm.user_prompt("I'm thirsty", world, scanned=["monster drink"])
    assert "Drinks, best first: monster drink (scanned, on the table); mug (on the table)" in text
    assert "Scanned with the webcam" in text and "thirsty" in llm.system_prompt()


def test_a_scanned_drink_not_on_the_table_is_offered_to_create():
    world = World()
    world.add("mug", 0.2, 0.1)
    assert llm.drinks(world, ["monster drink", "stapler"]) == [
        ("monster drink", "scanned, create it"), ("mug", "on the table")]


def test_picking_a_scanned_object_that_is_not_there_creates_it():
    world = World()
    world.add("red cube", 0.2, 0.1)
    plan = [{"skill": "pick", "object": "monster drink"}, {"skill": "place", "at": {"position": "front"}}]
    assert llm.create_missing(plan, world, ["monster drink"]) == [
        {"skill": "spawn", "object": "monster drink", "at": {"position": "front"}}]
    # On the table (also by a shorter name), or not a known object: left alone.
    world.add("monster drink", 0.25, 0.0)
    assert llm.create_missing(plan, world, ["monster drink"]) == plan
    cube = [{"skill": "pick", "object": "cube"}, {"skill": "place", "at": {"position": "left"}}]
    assert llm.create_missing(cube, world) == cube
    odd = [{"skill": "pick", "object": "unicorn"}]
    assert llm.create_missing(odd, world) == odd
