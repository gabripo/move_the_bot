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
import os
import re

import requests

from .skills import PLACE_HELP, SKILLS, validate
from .world import CATALOGUE, COLORS, World

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
        "- If the request is not something the arm can do, return an empty skills list and explain in \"say\".\n\n"
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
        "(table: empty)\n"
        "{\"skills\":[{\"skill\":\"spawn\",\"object\":\"bottle\",\"at\":{\"position\":\"center\"}}],"
        "\"say\":\"Here is a bottle.\"}\n"
    )


def user_prompt(text: str, world: World, hand=None) -> str:
    if world.objects:
        table = "; ".join(
            f"{o.name} at x={o.x:.2f} y={o.y:.2f}" + (" (in the gripper)" if o.held else "")
            for o in world.objects.values())
    else:
        table = "empty"
    lines = [f"Table: {table}"]
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


def ask(text: str, world: World, hand=None) -> tuple:
    """Ask the model for skills. Returns (skills, say, problems). Raises LLMError."""
    answer = chat([
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": user_prompt(text, world, hand)},
    ])
    return interpret(answer)


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
