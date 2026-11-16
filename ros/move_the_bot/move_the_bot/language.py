"""Rule-based understanding of everyday commands: text in, skill requests out.

This is the fast path. "pick up the apple and put it on the cube" is turned into skills in well
under a millisecond, with no model involved. Only when these rules do not understand a command
is the LLM asked (llm.py). Pure Python, no ROS.
"""
from __future__ import annotations

import re

from .world import ALIASES, CATALOGUE, COLORS, POSITION_ALIASES, POSITIONS, World, canonical_kind

NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "another": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "couple": 2, "few": 3,
}
MAX_COUNT = 6

SPAWN_VERBS = ("create", "spawn", "add", "make", "generate", "introduce", "give me", "i want",
               "i need", "show me", "insert", "summon")
PUT_VERBS = ("put", "place", "set", "drop", "move", "bring", "slide", "stack", "position",
             "leave", "lay", "carry", "transfer", "release", "throw")
PICK_VERBS = ("pick up", "pick", "grab", "grasp", "take", "get", "hold", "lift", "fetch", "catch",
              "seize")
MOVE_VERBS = ("move", "go", "reach", "travel", "approach", "hover", "point", "fly", "come")
REMOVE_VERBS = ("remove", "delete", "destroy", "erase", "get rid of", "eliminate")

DIRECTIONS = {
    "up": (0, 0, 1), "higher": (0, 0, 1), "upwards": (0, 0, 1), "upward": (0, 0, 1),
    "down": (0, 0, -1), "lower": (0, 0, -1), "downwards": (0, 0, -1), "downward": (0, 0, -1),
    "left": (0, 1, 0), "right": (0, -1, 0),
    "forward": (1, 0, 0), "forwards": (1, 0, 0), "further": (1, 0, 0), "farther": (1, 0, 0),
    "ahead": (1, 0, 0),
    "back": (-1, 0, 0), "backward": (-1, 0, 0), "backwards": (-1, 0, 0), "closer": (-1, 0, 0),
}

_COLOR_RE = "|".join(COLORS)
_COUNT_RE = "|".join(NUMBER_WORDS) + r"|\d+"
_EXTRA_KINDS: frozenset = frozenset()


def _compile_kinds() -> None:
    """The object names the rules recognise: the catalogue, its aliases and any extra kinds.
    Longest first, so "kaioken mug" (a scanned object) wins over "mug"."""
    global _KINDS, _KIND_RE, _NOUN
    _KINDS = sorted(set(CATALOGUE) | set(ALIASES) | _EXTRA_KINDS, key=len, reverse=True)
    _KIND_RE = "|".join(re.escape(k) for k in _KINDS)
    # "the red cube", "two apples", "another mug", "cube 2"
    _NOUN = re.compile(
        rf"\b(?:(?P<det>the|this|that|my|{_COUNT_RE})\s+)?(?:(?P<color>{_COLOR_RE})\s+)?"
        rf"(?P<kind>{_KIND_RE})(?:s|es)?\b(?!\s+(?:you|i|we|u)\b)(?:\s+(?:number\s+)?(?P<index>\d)\b(?!\s*(?:cm|mm|m\b|\.|\d)))?"
    )


def set_extra_kinds(kinds) -> None:
    """Object names to recognise besides the catalogue, such as objects scanned with the webcam
    ("kaioken mug"); without this the rules would read "a kaioken mug" as a plain mug."""
    global _EXTRA_KINDS
    extra = frozenset(" ".join(k.lower().split()) for k in kinds if k and k.strip())
    if extra != _EXTRA_KINDS:
        _EXTRA_KINDS = extra
        _compile_kinds()


_compile_kinds()
_PRONOUN = re.compile(r"\b(it|them|that one|this one|that|this)\b")
_FILLER = re.compile(
    r"\b(please|kindly|hey|hi|hello|ok|okay|robot|now|just|then|also|for me|thanks|thank you|"
    r"can you|could you|would you|will you|can u|i want you to|i need you to|i would like you to|"
    r"i'd like you to|go ahead and|try to)\b"
)
_NUMBER = r"-?\d+(?:\.\d+)?"


def _clean(text: str) -> str:
    t = text.lower().replace("’", "'")
    t = re.sub(r"(?<=\d),(?=\d)", ".", t)             # 0,2 -> 0.2
    t = re.sub(r"[!?]", ".", t)
    t = re.sub(r"\bcentimet(?:er|re)s?\b", "cm", t)
    t = re.sub(r"\bmillimet(?:er|re)s?\b", "mm", t)
    t = re.sub(r"\bmet(?:er|re)s?\b", "m", t)
    return t


def split_clauses(text: str) -> list:
    """'create an apple, then grab it and put it left' -> three clauses."""
    t = _clean(text)
    parts = re.split(r"\s*(?:;|\.(?!\d)|,|\band then\b|\bthen\b|\bafter that\b|\bafterwards\b|\band\b|&)\s*", t)
    clauses = []
    for part in parts:
        part = _FILLER.sub(" ", part)
        part = " ".join(part.split()).strip(" .")
        if part:
            clauses.append(part)
    return clauses


def _starts_with(clause: str, verbs) -> str | None:
    for verb in sorted(verbs, key=len, reverse=True):
        if clause == verb or clause.startswith(verb + " "):
            return verb
    return None


def _nouns(clause: str) -> list:
    """All object mentions in a clause, in order."""
    found = []
    for m in _NOUN.finditer(clause):
        det = m.group("det")
        count = 1
        definite = det in ("the", "this", "that", "my")
        if det and not definite:
            count = NUMBER_WORDS.get(det) or int(det)
        kind = canonical_kind(m.group("kind"))
        name = f"{m.group('color')} {kind}" if m.group("color") else kind
        if m.group("index"):
            name = f"{name} {m.group('index')}"
            definite = True
        found.append({
            "name": name, "kind": kind, "count": max(1, min(MAX_COUNT, count)),
            "definite": definite, "indefinite": bool(det) and not definite,
            "start": m.start(), "end": m.end(),
        })
    return found


def _place(clause: str, nouns: list, skip: dict | None = None) -> dict | None:
    """The destination mentioned in a clause, if any."""
    refs = [n for n in nouns if n is not skip]
    relations = (
        (r"(?:on top of|onto|on to|upon|on|atop)", "on"),
        (r"(?:above|over)", "above"),
        (r"(?:to the left of|on the left of|at the left of|left of)", "left_of"),
        (r"(?:to the right of|on the right of|at the right of|right of)", "right_of"),
        (r"(?:in front of|before)", "in_front_of"),
        (r"(?:behind|at the back of|in back of)", "behind"),
        (r"(?:next to|beside|besides|near to|near|close to|by|alongside|at|to|towards|toward)", "next_to"),
    )
    for n in refs:
        before = clause[: n["start"]]
        for pattern, relation in relations:
            if re.search(rf"\b{pattern}\s+$", before):
                return {"object": n["name"], "relation": relation}
    m = re.search(r"\b(?:on top of|onto|on|next to|beside|near|behind|in front of|left of|right of|above|over)\s+(it|that|this)\b", clause)
    if m:
        word = m.group(0).rsplit(" ", 1)[0]
        relation = {"on top of": "on", "onto": "on", "on": "on", "above": "above", "over": "above",
                    "behind": "behind", "in front of": "in_front_of", "left of": "left_of",
                    "right of": "right_of"}.get(word, "next_to")
        return {"object": "it", "relation": relation}
    m = re.search(rf"\b(?:at|to)\s+(?:x\s*=?\s*)?({_NUMBER})[\s,]+(?:y\s*=?\s*)?({_NUMBER})(?:[\s,]+(?:z\s*=?\s*)?({_NUMBER}))?", clause)
    if m:
        place = {"x": float(m.group(1)), "y": float(m.group(2))}
        if m.group(3):
            place["z"] = float(m.group(3))
        return place
    if re.search(r"\b(here|at my hand|in my hand|to my hand|where i point|where i am pointing|where my hand is|over here)\b", clause):
        return {"hand": True}
    names = sorted(list(POSITIONS) + list(POSITION_ALIASES), key=len, reverse=True)
    spot = "|".join(re.escape(n).replace(r"\ ", r"[\s-]") for n in names)
    m = re.search(rf"\b(?:to|on|at|in|into|towards|toward)\s+(?:the\s+|your\s+|its\s+)?(?:far\s+|very\s+)?({spot})\b(?!\s+of\b)", clause)
    if not m:
        m = re.search(rf"\b({spot})\s*(?:side|corner|part)?$", clause)
    if m:
        name = m.group(1).replace("-", " ")
        return {"position": POSITION_ALIASES.get(name, name)}
    return None


def _distance(clause: str) -> float:
    m = re.search(rf"({_NUMBER})\s*(cm|mm|m)\b", clause)
    if m:
        value = float(m.group(1)) * {"cm": 0.01, "mm": 0.001, "m": 1.0}[m.group(2)]
        return max(0.005, min(0.25, abs(value)))
    for word, n in NUMBER_WORDS.items():
        if re.search(rf"\b{word}\s+cm\b", clause):
            return n * 0.01
    if re.search(r"\b(a bit|a little|slightly|a tad|a touch)\b", clause):
        return 0.02
    if re.search(r"\b(a lot|much|far|way)\b", clause):
        return 0.10
    return 0.05


class _Context:
    """What earlier clauses of the same command have done."""

    def __init__(self, world: World):
        self.world = world
        self.created = set()            # names spawned earlier in this command
        self.holding = world.held       # what the gripper will hold at this point
        self.last = None                # what "it" refers to
        self.verb = None                # verb family of the previous clause
        self.place = None

    def exists(self, name: str) -> bool:
        return name in self.created or self.world.find(name) is not None

    def it(self) -> str:
        return self.last or self.holding or self.world.last or "it"


def _spawn(nouns, place, ctx) -> list:
    out = []
    for n in nouns:
        for _ in range(n["count"]):
            skill = {"skill": "spawn", "object": n["name"]}
            if place and not (place.get("object") == n["name"]):
                skill["at"] = dict(place)
            out.append(skill)
        ctx.created.add(n["name"])
        ctx.last = n["name"]
    return out


def _carry(target: str | None, place: dict | None, ctx) -> list:
    """Pick `target` (unless already held) and put it at `place`."""
    out = []
    target = target or ctx.it()
    if ctx.holding is None or (target != "it" and ctx.holding != target
                               and not _same(ctx, ctx.holding, target)):
        out.append({"skill": "pick", "object": target})
    skill = {"skill": "place"}
    if place:
        skill["at"] = place
    out.append(skill)
    ctx.holding = None
    ctx.last = target if target != "it" else ctx.last
    return out


def _same(ctx, held: str, reference: str) -> bool:
    obj = ctx.world.find(reference)
    return obj is not None and obj.name == held


def _clause(clause: str, ctx: _Context) -> list | None:
    nouns = _nouns(clause)
    pronoun = _PRONOUN.search(clause)

    # A clause without a verb continues the previous one: "... then to the bottle", "and a mug".
    families = SPAWN_VERBS + PUT_VERBS + PICK_VERBS + MOVE_VERBS + REMOVE_VERBS
    if ctx.verb and not _starts_with(clause, families) and re.match(
            rf"^(?:to|on|onto|over|above|towards|at|the|{_COUNT_RE}|{_COLOR_RE}|{_KIND_RE})\b", clause):
        if not re.match(r"^(stop|open|close|home|reset|clear|go|let)\b", clause):
            clause = f"{ctx.verb} {clause}"
            nouns = _nouns(clause)
            pronoun = _PRONOUN.search(clause)

    # ---- one-word and fixed commands
    if re.match(r"^(stop|halt|freeze|cancel|abort|wait|hold on|enough)\b", clause):
        return [{"skill": "stop"}]
    if re.match(r"^(reset|start over|restart|clean up|clear)\b", clause) and not nouns:
        return [{"skill": "reset"}]
    if re.match(r"^(?:clear|empty|clean|wipe|reset)\s+(?:the\s+)?(?:table|scene|everything|all|workspace|desk)\b", clause):
        return [{"skill": "reset"}]
    if re.match(r"^(?:remove|delete|destroy|erase|get rid of|eliminate)\s+(?:everything|all|every object|all(?: the)? objects|them all)\b", clause):
        return [{"skill": "reset"}]
    if re.match(r"^(?:(?:go|move|return|get|come)\s+)?(?:back\s+)?(?:to\s+)?(?:the\s+|your\s+)?(?:home|rest|resting|start|starting|initial|neutral)(?:\s+(?:position|pose))?$", clause) or clause in ("rest", "relax", "go back"):
        return [{"skill": "home"}]
    m = re.match(r"^(open|close|shut)\s*(?:up\s+)?(?:the\s+|your\s+)?(?:gripper|hand|claw|fingers|grip|jaw|jaws)?$", clause)
    if m:
        return [{"skill": "gripper", "state": "open" if m.group(1) == "open" else "close"}]
    if re.match(r"^(let go|let it go|release|drop|put down|put it down|drop it|release it|let go of it|set it down|place it down)$", clause):
        ctx.verb = "put"
        if ctx.holding:
            ctx.holding = None
            return [{"skill": "place"}]
        return [{"skill": "gripper", "state": "open"}]

    # ---- remove
    if _starts_with(clause, REMOVE_VERBS):
        ctx.verb = "remove"
        if nouns:
            return [{"skill": "remove", "object": n["name"]} for n in nouns]
        if pronoun:
            return [{"skill": "remove", "object": ctx.it()}]
        return None

    # ---- create
    verb = _starts_with(clause, SPAWN_VERBS)
    if verb:
        ctx.verb = "create"
        rest = clause[len(verb):].strip()
        if nouns:
            first_object = nouns[0]
            anchors = [n for n in nouns[1:] if n["definite"] or ctx.exists(n["name"])]
            place = _place(clause, nouns, skip=first_object)
            targets = [n for n in nouns if n not in anchors or n is first_object]
            if place and "object" in place:
                targets = [n for n in targets if n["name"] != place["object"] or n is first_object]
            return _spawn(targets, place, ctx)
        # An object the catalogue does not know: "create a banana"
        m = re.match(rf"^(?:(?:{_COUNT_RE}|the|some)\s+)?(?:new\s+)?([a-z][a-z \-]{{1,30}}?)(?=$|\s+(?:on|at|to|in|next|near|behind|left|right|here|over|above|beside)\b)", rest)
        if m:
            name = m.group(1).strip()
            if name and len(name.split()) <= 2 and not set(name.split()) & {
                    "it", "one", "something", "object", "thing", "stuff", "with", "of", "for",
                    "everything", "all", "me", "you", "and", "from"}:
                place = _place(clause, [])
                skill = {"skill": "spawn", "object": name}
                if place:
                    skill["at"] = place
                ctx.created.add(name)
                ctx.last = name
                return [skill]
        return None

    # ---- pick
    verb = _starts_with(clause, PICK_VERBS)
    if verb and not (verb in ("get", "take") and re.match(r"^(get|take)\s+(rid|back|home|a break)", clause)):
        ctx.verb = "pick"
        # Something the catalogue does not know ("grab the banana"): pass the name on, so the
        # robot can answer that there is no such thing instead of grabbing something else.
        unknown = re.match(
            rf"^(?:up\s+)?(?:the|this|that|my|a|an)\s+([a-z][a-z\-]{{1,20}}(?:\s+[a-z][a-z\-]{{1,20}})?)$",
            clause[len(verb):].strip())
        if nouns:
            target = nouns[0]["name"]
        elif unknown and not pronoun and not set(unknown.group(1).split()) & {
                "gripper", "hand", "arm", "robot", "object", "thing", "one", "table"}:
            ctx.last = unknown.group(1)
            return [{"skill": "pick", "object": unknown.group(1)}]
        elif pronoun or len(ctx.world.objects) + len(ctx.created) >= 1:
            target = ctx.it()
            if target == "it" and not ctx.world.last and len(ctx.world.objects) == 1:
                target = next(iter(ctx.world.objects))
        else:
            return [{"skill": "gripper", "state": "close"}]
        out = []
        if ctx.holding and not _same(ctx, ctx.holding, target) and ctx.holding != target:
            out.append({"skill": "place"})
        out.append({"skill": "pick", "object": target})
        ctx.holding = ctx.world.find(target).name if ctx.world.find(target) else target
        ctx.last = target if target != "it" else ctx.last
        # "take the apple to the left": a pick verb with a destination is a carry.
        place = _place(clause, nouns, skip=nouns[0] if nouns else None)
        if place and verb in ("take", "get", "carry", "fetch", "lift") and not (
                "object" in place and nouns and place["object"] == nouns[0]["name"]):
            out.append({"skill": "place", "at": place})
            ctx.holding = None
        return out

    # ---- relative arm motion: "move up 5 cm", "a bit to the left", "go down"
    m = re.match(
        r"^(?:(?:move|go|shift|nudge|slide|come|lift|raise|lower)\s+)?(?:the\s+(?:arm|gripper|hand|robot)\s+)?"
        r"(?:(?:a bit|a little|slightly|a lot|much|far|a tad|a touch)\s+)?(?:(?:\d+(?:\.\d+)?|" + "|".join(NUMBER_WORDS) + r")\s*(?:cm|mm|m)\s+)?(?:more\s+)?(?:to\s+the\s+|to\s+your\s+)?"
        r"(" + "|".join(DIRECTIONS) + r")(?:wards?)?\b(?!\s+(?:of|side|corner)\b)(?P<tail>.*)$", clause)
    relative_only = m and not nouns and not re.match(r"^(?:move|go)\s+to\s+the\s+", clause) and not re.search(
        r"\b(?:to|on|at)\s+the\s+(?:front|back)\b", clause)
    if relative_only and re.match(r"^\s*(?:(?:by\s+)?(?:\d+(?:\.\d+)?|" + "|".join(NUMBER_WORDS) + r")\s*(?:cm|mm|m)|a bit|a little|slightly|a lot|more|please)?\s*$", m.group("tail")):
        direction = DIRECTIONS[m.group(1)]
        if re.match(r"^(raise|lift)\b", clause):
            direction = (0, 0, 1)
        elif re.match(r"^lower\b", clause) and m.group(1) == "lower":
            direction = (0, 0, -1)
        d = _distance(clause)
        ctx.verb = "move"
        return [{"skill": "move_by", "dx": direction[0] * d, "dy": direction[1] * d, "dz": direction[2] * d}]

    # ---- put / place / move <object> ...
    verb = _starts_with(clause, PUT_VERBS)
    if verb:
        after = clause[len(verb):].strip()
        object_first = bool(nouns) and re.match(
            rf"^(?:down\s+)?(?:(?:the|this|that|my|{_COUNT_RE})\s+)?(?:(?:{_COLOR_RE})\s+)?(?:{_KIND_RE})", after)
        pronoun_first = re.match(r"^(?:down\s+)?(it|them|that|this)\b", after)
        if object_first:
            target = nouns[0]
            place = _place(clause, nouns, skip=target)
            others = nouns[1:]
            if place and "object" in place:
                others = [n for n in others if n["name"] != place["object"]]
            # "put an apple on the left" creates one; "put the apple on the left" moves it,
            # unless there is no apple yet.
            if verb != "stack" and (target["indefinite"] or not ctx.exists(target["name"])) \
                    and verb not in ("drop", "release", "move", "bring", "slide", "carry", "transfer") \
                    or (target["indefinite"] and target["count"] > 1):
                ctx.verb = "create"
                return _spawn([target] + [n for n in others if n["indefinite"]], place, ctx)
            ctx.verb = "put"
            return _carry(target["name"], place, ctx)
        if pronoun_first or re.match(r"^(?:it\s+)?down\b", after):
            ctx.verb = "put"
            place = _place(clause, nouns)
            return _carry(None, place, ctx)
        if verb in ("put", "place", "set", "drop", "leave", "lay", "release", "stack") and (ctx.holding or pronoun):
            place = _place(clause, nouns)
            if place:
                ctx.verb = "put"
                return _carry(None, place, ctx)

    # ---- move the arm somewhere
    verb = _starts_with(clause, MOVE_VERBS)
    if verb:
        ctx.verb = verb
        m = re.search(rf"\bto\s+(?:x\s*=?\s*)?({_NUMBER})[\s,]+(?:y\s*=?\s*)?({_NUMBER})[\s,]+(?:z\s*=?\s*)?({_NUMBER})", clause)
        if m:
            return [{"skill": "move_to", "at": {"x": float(m.group(1)), "y": float(m.group(2)), "z": float(m.group(3))}}]
        if nouns:
            ctx.last = nouns[0]["name"]
            return [{"skill": "move_to", "at": {"object": nouns[0]["name"], "relation": "above"}}]
        if pronoun and re.search(r"\b(to|over|above|towards|toward|at)\s+(it|that|this)\b", clause):
            return [{"skill": "move_to", "at": {"object": ctx.it(), "relation": "above"}}]
        place = _place(clause, nouns)
        if place:
            return [{"skill": "move_to", "at": place}]
    return None


def parse(text: str, world: World | None = None) -> list | None:
    """Skill requests for a command, or None when the rules do not understand all of it."""
    ctx = _Context(world or World())
    skills = []
    clauses = split_clauses(text)
    if not clauses:
        return None
    for clause in clauses:
        result = _clause(clause, ctx)
        if result is None:
            return None
        skills.extend(result)
        if any(s["skill"] in ("stop", "reset") for s in result):
            ctx.holding = None
    return skills or None
