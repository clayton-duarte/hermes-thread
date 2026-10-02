"""The real classify-and-apply work, run only on the background worker
thread — never on the hook's calling thread.

``classify_and_apply`` is intentionally fail-open: any exception from the
model call or from parsing leaves the DB untouched (the transition is simply
skipped) and is logged, never raised. A broken classifier must not break the
chat, and because the hook already returned before this runs, there is
nothing left to raise into anyway.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict

import db
from prompt import JSON_SCHEMA, build_prompt, parse_result

logger = logging.getLogger(__name__)

# Signature expected of the plugin LLM facade's structured-completion call:
# complete_structured(instructions=..., input=[...], json_schema=...,
#                     task=...) -> result
# result.parsed is a dict (or None if parsing/validation failed upstream).
ClassifyCaller = Callable[..., Any]


def classify_and_apply(
    con,
    llm: ClassifyCaller,
    *,
    session_id: str,
    turn_id: str,
    message: str,
) -> None:
    """Load the session's ask list, classify ``message`` against it, and apply
    whichever of the five transitions the model picked. Never raises."""
    try:
        lists = db.get_lists(con, session_id)
        prompt = build_prompt(message, lists)
        result = llm(
            instructions=prompt["instructions"],
            input=[{"type": "text", "text": prompt["input_text"]}],
            json_schema=JSON_SCHEMA,
            task="thread_classify",
        )
        parsed = parse_result(getattr(result, "parsed", None))
        if parsed is None:
            logger.warning(
                "thread_classify: unparseable/invalid model result, skipping turn %s",
                turn_id,
            )
            return
        _apply(
            con, parsed, lists, session_id=session_id, turn_id=turn_id, message=message
        )
    except Exception:
        logger.exception(
            "thread_classify: classification failed for turn %s, DB left untouched",
            turn_id,
        )


def _apply(
    con,
    parsed: Dict[str, Any],
    lists: Dict[str, Any],
    *,
    session_id: str,
    turn_id: str,
    message: str,
) -> None:
    transition = parsed["transition"]
    if transition == "attach":
        db.apply_attach(con, session_id=session_id, turn_id=turn_id)
    elif transition == "create":
        title = parsed.get("title") or message[:80]
        db.record_ask(con, session_id=session_id, title=title, turn_id=turn_id)
    elif transition == "move_pointer":
        ask_id = parsed.get("ask_id")
        if ask_id:
            db.apply_move_pointer(
                con, session_id=session_id, ask_id=ask_id, turn_id=turn_id
            )
    elif transition == "complete":
        db.apply_complete(con, session_id=session_id, turn_id=turn_id)
    elif transition == "reopen":
        ask_id = parsed.get("ask_id")
        if ask_id:
            db.apply_reopen(con, session_id=session_id, ask_id=ask_id, turn_id=turn_id)
