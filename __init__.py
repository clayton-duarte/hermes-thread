"""thread plugin entrypoint — registers the thread_classify auxiliary task.

register(ctx) is called once by the plugin loader (hermes_cli/plugins.py).
"""

from __future__ import annotations


def register(ctx, **kwargs) -> None:
    """Register the thread_classify auxiliary LLM task.

    Namespaced key (not a built-in collision): classifies each user message
    against the session's ask list using a configured (cheap) model, via
    auxiliary.thread_classify.* config.
    """
    ctx.register_auxiliary_task(
        "thread_classify",
        display_name="Thread ask classifier",
        description="Classifies each user message against the session's ask list.",
        defaults={"provider": "auto", "model": "", "timeout": 30},
    )
