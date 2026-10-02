import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from __init__ import register  # noqa: E402


class StubCtx:
    """Stand-in for the plugin loader's ctx — no import of hermes_cli."""

    def __init__(self):
        self.calls = []
        self.hooks = []
        self.llm = object()

    def register_auxiliary_task(self, key, **kwargs):
        self.calls.append((key, kwargs))

    def register_hook(self, hook_name, callback):
        self.hooks.append((hook_name, callback))


def test_register_calls_register_auxiliary_task_with_namespaced_key():
    ctx = StubCtx()
    register(ctx)
    assert len(ctx.calls) == 1
    key, kwargs = ctx.calls[0]
    assert key == "thread_classify"


def test_register_sets_display_name_and_description():
    ctx = StubCtx()
    register(ctx)
    _, kwargs = ctx.calls[0]
    assert kwargs["display_name"] == "Thread ask classifier"
    assert "classifies" in kwargs["description"].lower()


def test_register_defaults_use_auto_provider_and_empty_model():
    ctx = StubCtx()
    register(ctx)
    _, kwargs = ctx.calls[0]
    defaults = kwargs["defaults"]
    assert defaults["provider"] == "auto"
    assert defaults["model"] == ""
    assert defaults["timeout"] == 30
