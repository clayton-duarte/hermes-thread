"""The load-bearing test: post_llm_call must return in well under 5ms, even
when the classifier is stubbed to sleep for 2s. Proves the hook enqueues and
returns rather than ever calling the model synchronously.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import importlib  # noqa: E402


def _fresh_thread_module(monkeypatch, tmp_path):
    """Reimport the thread package fresh with its globals reset and its DB
    pointed at a tmp file, so this test never touches a real ~/.hermes."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    for mod in ("__init__", "db", "classify", "prompt", "filter", "worker"):
        sys.modules.pop(mod, None)
    import __init__ as thread_mod  # noqa: E402
    import db as db_mod  # noqa: E402

    importlib.reload(db_mod)
    importlib.reload(thread_mod)
    return thread_mod


class SlowStubCtx:
    def __init__(self, llm):
        self.llm = llm

    def register_auxiliary_task(self, key, **kwargs):
        pass

    def register_hook(self, hook_name, callback):
        self.callback = callback


class SlowLlm:
    """A stand-in for ctx.llm whose complete_structured call sleeps for 2s —
    this is the thing that must NEVER run on the hook's calling thread."""

    def complete_structured(self, **kwargs):
        time.sleep(2)
        raise AssertionError("classifier should run on the worker thread, not here")


def test_post_llm_call_returns_in_under_5ms_even_with_slow_classifier(
    monkeypatch, tmp_path
):
    thread_mod = _fresh_thread_module(monkeypatch, tmp_path)
    ctx = SlowStubCtx(SlowLlm())
    thread_mod.register(ctx)

    start = time.perf_counter()
    ctx.callback(
        session_id="s1",
        turn_id="t1",
        user_message="Can you add retry logic to the upload handler?",
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert elapsed_ms < 5, f"post_llm_call took {elapsed_ms:.2f}ms, must be under 5ms"
