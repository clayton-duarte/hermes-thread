"""Pure prompt-shaping for the thread_classify auxiliary task.

Kept free of DB/LLM imports so it unit-tests with plain dicts. The three-state
shape (CURRENT full title / OPEN titles-only / COMPLETED titles-only,
collapsed) is deliberate: it is cheap (titles only, except current) and keeps
attention on the default case (attach to current).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

TRANSITIONS = ("attach", "move_pointer", "create", "complete", "reopen")

JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "transition": {"type": "string", "enum": list(TRANSITIONS)},
        "ask_id": {"type": ["string", "null"]},
        "title": {"type": ["string", "null"]},
    },
    "required": ["transition"],
}

INSTRUCTIONS = (
    "You track a running list of the user's asks in this conversation. Given the "
    "latest user message and the current ask lists, decide exactly one transition:\n"
    "- attach: the message continues the CURRENT ask (the default for most messages).\n"
    "- move_pointer: the message returns to an existing OPEN ask, which becomes\n"
    "  current.\n"
    "- create: the message starts a new ask; the old current (if any) becomes open.\n"
    "- complete: the message indicates the CURRENT ask is finished.\n"
    "- reopen: the message explicitly reopens a COMPLETED ask, which becomes current.\n"
    "Only consider OPEN asks when the message signals a subject change. Only consider "
    "COMPLETED asks when the user is very explicit about reopening one. When in doubt, "
    "prefer attach. Discourse markers (e.g. 'back to the', 'is done', 'new idea') are "
    "hints that raise your confidence, not hard rules — a message like 'strike out all "
    "that were resolved' is itself a new ask, not a completion of anything.\n"
    "Return ask_id when the transition is move_pointer or reopen (the id of the "
    "existing ask you are pointing to). Return title when the transition is create."
)


def _title_only(asks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"id": a["id"], "title": a["title"]} for a in asks]


def build_prompt(message: str, lists: Dict[str, Any]) -> Dict[str, Any]:
    """Shape (message, {current, open, completed}) into the structured-completion
    call's input text. Returns {"instructions", "input_text"} — both plain
    strings so the caller decides how to wrap them for ctx.llm."""
    current = lists.get("current")
    open_asks = lists.get("open") or []
    completed = lists.get("completed") or []

    lines = [f"MESSAGE: {message}", ""]
    if current:
        lines.append(f"CURRENT (full): id={current['id']} title={current['title']!r}")
    else:
        lines.append("CURRENT: none")
    lines.append(f"OPEN (titles only): {_title_only(open_asks)}")
    lines.append(f"COMPLETED (titles only, collapsed): {_title_only(completed)}")

    return {"instructions": INSTRUCTIONS, "input_text": "\n".join(lines)}


def parse_result(parsed: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Validate a classifier's parsed JSON into a normalized transition dict,
    or None if it is malformed (caller should then fail-open / no-op)."""
    if not isinstance(parsed, dict):
        return None
    transition = parsed.get("transition")
    if transition not in TRANSITIONS:
        return None
    return {
        "transition": transition,
        "ask_id": parsed.get("ask_id"),
        "title": parsed.get("title"),
    }
