"""The LLM fallback: asked only when the rules in language.py do not understand a command.

Two back-ends, chosen with the LLM_BACKEND environment variable:

  ollama  (default) a local model served by Ollama. Nothing leaves the machine.
  openai  any OpenAI-compatible endpoint: NVIDIA NIM (cloud or a local NIM container),
          vLLM, llama.cpp, LM Studio...

The model must answer with JSON: {"skills": [...], "say": "optional short reply"}.
Whatever it answers is validated before the robot moves.
"""
from __future__ import annotations

import json
import math
import os
import re

import requests

from .skills import PLACE_HELP, SKILLS, validate
from .world import CATALOGUE, COLORS, POSITIONS, World

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b-instruct-q4_K_M")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", os.environ.get("NVIDIA_API_KEY", ""))
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "meta/llama-3.1-8b-instruct")
BACKEND = os.environ.get("LLM_BACKEND", "ollama").strip().lower()
TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "90"))
MAX_SKILLS = 12

# Older configurations pointed OLLAMA_URL at the /api/generate endpoint.
OLLAMA_URL = re.sub(r"/api/(generate|chat)$", "", OLLAMA_URL)


# Words that make an object something to drink ("monster drink", "coke can", "mug").
DRINK_WORDS = ("drink", "monster", "red bull", "energy", "can", "soda", "cola", "coke", "pepsi", "sprite",
               "fanta", "beer", "juice", "water", "lemonade", "bottle", "mug", "cup", "glass", "coffee",
               "tea", "milk")


def is_drink(name: str) -> bool:
    words = " " + " ".join(re.sub(r"\d+", " ", name.lower()).split()) + " "
    return any(f" {w} " in words or f" {w}s " in words for w in DRINK_WORDS)


BROUGHT = 0.07     # metres from the front of the table: a drink there was brought to the user


def drinks(world: World, scanned=()) -> list:
    """What to bring someone thirsty, best first: the drinks on the table (the user's own scanned
    ones first), then scanned drinks to create; last, the drinks already brought to the front
    ("I'm still thirsty" means another one). [(name, note)]."""
    scanned = [" ".join(k.lower().split()) for k in scanned]
    fx, fy = POSITIONS["front"]
    on_table = [o for o in world.objects.values() if (is_drink(o.name) or is_drink(o.kind)) and not o.held]
    brought = [o for o in on_table if math.hypot(o.x - fx, o.y - fy) < BROUGHT]
    waiting = [o for o in on_table if o not in brought]
    best = [(o.name, "scanned, on the table") for o in waiting if o.kind in scanned]
    best += [(o.name, "on the table") for o in waiting if o.kind not in scanned]
    best += [(k, "scanned, create it") for k in scanned
             if is_drink(k) and not any(o.kind == k for o in on_table)]
    best += [(o.name, "already brought to the user") for o in brought]
    return best


class LLMError(Exception):
    """The model could not be reached or its answer could not be used."""


def model_name() -> str:
    return OPENAI_MODEL if BACKEND == "openai" else OLLAMA_MODEL


def system_prompt() -> str:
    skills = "\n".join(f"- {name}: {text}" for name, text in SKILLS.items())
    return (
        "You control a small robot arm on a table. Turn the user's request into a list of skills.\n\n"
        f"SKILLS\n{skills}\n\n"
        f"PLACES\n{PLACE_HELP}\n\n"
        f"OBJECTS YOU CAN CREATE\n{', '.join(CATALOGUE)}. Colours: {', '.join(COLORS)} "
        "(write them before the object: \"red cube\").\n\n"
        "RULES\n"
        "- Answer with JSON only: {\"skills\": [ ... ], \"say\": \"one short sentence\"}.\n"
        "- Each skill is an object with a \"skill\" field and its own fields, in the order to run them.\n"
        "- To move an object: first {\"skill\":\"pick\",\"object\":...}, then {\"skill\":\"place\",\"at\":...}.\n"
        "- The gripper holds one object at a time.\n"
        "- Only pick objects that are on the table (listed below) or that you create first.\n"
        "- If the request is not something the arm can do, return an empty skills list and explain in \"say\".\n"
        "- If the user is thirsty or wants a drink, bring the FIRST drink of the \"Drinks\" line: pick it and "
        "place it at the front (towards the user); if it is not on the table yet, create it at the front. "
        "Without a Drinks line, create a bottle.\n"
        "- \"Still thirsty\", \"another drink\": a different drink from the one already brought: the first drink "
        "of the line that is not \"already brought\". If there is none, create a bottle.\n"
        "- \"A real drink\", \"a proper drink\", \"something better\": the user's own drink, the first \"scanned\" one "
        "of the line (pick it, or create it if it says so), even if another drink comes before it.\n\n"
        "EXAMPLES\n"
        "User: tidy up, put everything on the left\n"
        "(table: apple, cube)\n"
        "{\"skills\":[{\"skill\":\"pick\",\"object\":\"apple\"},{\"skill\":\"place\",\"at\":{\"position\":\"left\"}},"
        "{\"skill\":\"pick\",\"object\":\"cube\"},{\"skill\":\"place\",\"at\":{\"position\":\"left\"}}],"
        "\"say\":\"Moving both objects to the left.\"}\n"
        "User: build a tower\n"
        "(table: red cube, blue cube, can)\n"
        "{\"skills\":[{\"skill\":\"pick\",\"object\":\"red cube\"},{\"skill\":\"place\",\"at\":{\"object\":\"blue cube\",\"relation\":\"on\"}}],"
        "\"say\":\"Stacking the red cube on the blue cube.\"}\n"
        "User: I'm thirsty\n"
        "(table: mug, apple. Drinks, best first: mug (on the table); monster drink (scanned, create it))\n"
        "{\"skills\":[{\"skill\":\"pick\",\"object\":\"mug\"},{\"skill\":\"place\",\"at\":{\"position\":\"front\"}}],"
        "\"say\":\"Here is your mug.\"}\n"
        "User: I'm still thirsty!\n"
        "(table: mug, monster drink. Drinks, best first: monster drink (scanned, on the table); mug (already brought to the user))\n"
        "{\"skills\":[{\"skill\":\"pick\",\"object\":\"monster drink\"},{\"skill\":\"place\",\"at\":{\"position\":\"front\"}}],"
        "\"say\":\"Here is your monster drink.\"}\n"
        "User: I'm thirsty\n"
        "(table: empty)\n"
        "{\"skills\":[{\"skill\":\"spawn\",\"object\":\"bottle\",\"at\":{\"position\":\"center\"}}],"
        "\"say\":\"Here is a bottle.\"}\n"
    )


def user_prompt(text: str, world: World, hand=None, scanned=()) -> str:
    if world.objects:
        table = "; ".join(
            f"{o.name} at x={o.x:.2f} y={o.y:.2f}" + (" (in the gripper)" if o.held else "")
            for o in world.objects.values())
    else:
        table = "empty"
    lines = [f"Table: {table}"]
    if scanned:
        lines.append("Scanned with the webcam (the user's own objects; you can create them too): " + ", ".join(scanned))
    best = drinks(world, scanned)
    if best:
        lines.append("Drinks, best first: " + "; ".join(f"{name} ({note})" for name, note in best))
    if hand is not None:
        lines.append(f"The user's hand points at x={hand[0]:.2f} y={hand[1]:.2f}")
    lines.append(f"User: {text}")
    return "\n".join(lines)


def extract_json(text: str):
    """The first JSON object or array in a model answer (models like to add prose around it)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        while start != -1:
            depth, in_string, escaped = 0, False, False
            for i in range(start, len(text)):
                ch = text[i]
                if in_string:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        in_string = False
                elif ch == '"':
                    in_string = True
                elif ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            break
            start = text.find(opener, start + 1)
    raise LLMError("the model did not answer with JSON")


def interpret(answer: str) -> tuple:
    """Model answer -> (valid skill requests, what to say, problems found)."""
    data = extract_json(answer)
    say = ""
    if isinstance(data, dict):
        say = str(data.get("say") or data.get("message") or "")[:200]
        items = data.get("skills")
        if items is None:
            items = data.get("actions")
        if items is None:
            items = [data] if ("skill" in data or "action" in data) else []
    else:
        items = data
    if not isinstance(items, list):
        items = [items]
    skills, problems = [], []
    for item in items[:MAX_SKILLS]:
        try:
            skills.append(validate(item))
        except ValueError as e:
            problems.append(f"{e} in {json.dumps(item)[:120]}")
    return skills, say, problems


def chat(messages: list) -> str:
    """Send a conversation to the configured back-end and return the model's text."""
    try:
        if BACKEND == "openai":
            headers = {"Content-Type": "application/json"}
            if OPENAI_API_KEY:
                headers["Authorization"] = f"Bearer {OPENAI_API_KEY}"
            r = requests.post(
                f"{OPENAI_BASE_URL}/chat/completions", headers=headers, timeout=TIMEOUT,
                json={"model": OPENAI_MODEL, "messages": messages, "temperature": 0.1,
                      "max_tokens": 600, "stream": False})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"] or ""
        r = requests.post(
            f"{OLLAMA_URL}/api/chat", timeout=TIMEOUT,
            json={"model": OLLAMA_MODEL, "messages": messages, "stream": False, "format": "json",
                  "options": {"temperature": 0.1, "num_predict": 600}, "keep_alive": "30m"})
        r.raise_for_status()
        return r.json()["message"]["content"] or ""
    except requests.Timeout:
        raise LLMError(f"the model did not answer within {TIMEOUT:.0f} s") from None
    except requests.ConnectionError:
        where = OPENAI_BASE_URL if BACKEND == "openai" else OLLAMA_URL
        raise LLMError(f"cannot reach the model at {where}") from None
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as e:
        raise LLMError(f"model error: {e}") from None


def ask(text: str, world: World, hand=None, scanned=()) -> tuple:
    """Ask the model for skills. Returns (skills, say, problems). Raises LLMError."""
    answer = chat([
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": user_prompt(text, world, hand, scanned)},
    ])
    skills, say, problems = interpret(answer)
    return create_missing(skills, world, scanned), say, problems


def _overlaps(a: str, b: str) -> bool:
    """'monster drink' and 'monster', 'red bull can' and 'red bull': one name inside the other."""
    a, b = f" {a} ", f" {b} "
    return a != b and (a in b or b in a)


def create_missing(skills: list, world: World, scanned=()) -> list:
    """Models like to pick a scanned object that is not on the table yet ("bring me my monster
    drink"): such a pick, and the place after it, become creating it where it was to go. A name
    a little off ("monster drink" for the scanned "monster") becomes the real one first."""
    scanned = [" ".join(k.lower().split()) for k in scanned]
    known = set(scanned) | set(CATALOGUE)
    there = set()                       # created earlier in this plan
    out, i = [], 0
    while i < len(skills):
        s = skills[i]
        name = str(s.get("object", "")).lower()
        if name and s.get("skill") in ("pick", "spawn", "remove") and name not in known and world.find(name) is None:
            # "monster drink" for the scanned "monster" (or the other way round): the real name
            near = [o.name for o in world.objects.values() if _overlaps(name, o.name)] + \
                   [k for k in scanned if _overlaps(name, k)]
            if near:
                name = near[0]
                s = {**s, "object": name}
        if s.get("skill") == "pick" and name in known and name not in there and world.find(name) is None:
            follows = skills[i + 1] if i + 1 < len(skills) else None
            if follows and follows.get("skill") == "place":
                out.append({"skill": "spawn", "object": name, **({"at": follows["at"]} if follows.get("at") else {})})
                i += 2
            else:
                out += [{"skill": "spawn", "object": name}, s]
                i += 1
            there.add(name)
            continue
        if s.get("skill") == "spawn" and name:
            there.add(name)
        out.append(s)
        i += 1
    return out


def warm_up() -> str | None:
    """Make sure the model is available (Ollama downloads it on first use). Returns an error or None."""
    try:
        if BACKEND == "openai":
            return None
        r = requests.post(f"{OLLAMA_URL}/api/pull", json={"name": OLLAMA_MODEL, "stream": False},
                          timeout=1800)
        r.raise_for_status()
        return None
    except requests.RequestException as e:
        return str(e)
