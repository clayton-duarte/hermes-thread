"""thread plugin entrypoint — registers the thread_classify auxiliary task and
the post_llm_call hook.

register(ctx) is called once by the plugin loader (hermes_cli/plugins.py).

The hook (``_on_post_llm_call``) is the load-bearing piece of this plugin: it
must return in well under the turn-finalization budget. It does the free
stage-1 filter synchronously, then enqueues the survivor onto a background
worker and returns — no model call, no DB write, nothing blocking ever
happens on the calling thread.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import db
from classify import classify_and_apply
from filter import is_noise, strip_attachments, unwrap_multimodal
from worker import ThreadWorker

logger = logging.getLogger(__name__)

# Module-level singletons: one DB connection and one background worker per
# process, built lazily so importing this module (e.g. from tests) never
# touches a real ~/.hermes or opens a thread.
_worker: Optional[ThreadWorker] = None
_con = None
_llm = None


def _get_con():
    global _con
    if _con is None:
        _con = db.connect()
    return _con


def _classify_item(item: Dict[str, Any]) -> None:
    classify_and_apply(
        _get_con(),
        _llm.complete_structured,
        session_id=item["session_id"],
        turn_id=item["turn_id"],
        message=item["message"],
    )


def _get_worker() -> ThreadWorker:
    global _worker
    if _worker is None:
        _worker = ThreadWorker(_classify_item)
    return _worker


def _on_post_llm_call(
    *,
    session_id: str = "",
    turn_id: str = "",
    user_message: str = "",
    **kwargs: Any,
) -> None:
    """post_llm_call hook callback. MUST return in milliseconds — see the
    module docstring. Any model call belongs only in classify.py, invoked
    from the background worker thread, never from here."""
    text = unwrap_multimodal(user_message or "")
    text = strip_attachments(text)
    noise, _why = is_noise(text)
    if noise:
        return
    _get_worker().enqueue(
        {"session_id": session_id, "turn_id": turn_id, "message": text}
    )


def register(ctx, **kwargs) -> None:
    """Register the thread_classify auxiliary LLM task and the post_llm_call
    hook.

    Namespaced key (not a built-in collision): classifies each user message
    against the session's ask list using a configured (cheap) model, via
    auxiliary.thread_classify.* config.
    """
    global _llm
    _llm = ctx.llm
    ctx.register_auxiliary_task(
        "thread_classify",
        display_name="Thread ask classifier",
        description="Classifies each user message against the session's ask list.",
        defaults={"provider": "auto", "model": "", "timeout": 30},
    )
    ctx.register_hook("post_llm_call", _on_post_llm_call)
