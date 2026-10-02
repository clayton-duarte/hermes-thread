"""Background worker: a single daemon thread draining a queue so the
``post_llm_call`` hook can enqueue-and-return in well under a millisecond.

No network call ever happens on the hook's calling thread. ``classify_fn`` is
whatever does the real work (see classify.py); it is called from the worker
thread, never from ``enqueue``.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class ThreadWorker:
    """Owns one background thread and an unbounded queue. ``enqueue`` only
    does a ``queue.Queue.put`` (O(1), no lock contention worth measuring) and
    returns; the thread calls ``classify_fn(item)`` for each item, catching
    and logging (never raising) any exception so a broken classifier can
    never take down the worker thread."""

    def __init__(self, classify_fn: Callable[[Any], None]):
        self._classify_fn = classify_fn
        self._queue: "queue.Queue[Any]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _ensure_started(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="thread-classify-worker"
            )
            self._thread.start()

    def enqueue(self, item: Any) -> None:
        """Non-blocking: put the item on the queue and return immediately.
        This is the only thing the hook's calling thread does."""
        self._ensure_started()
        self._queue.put_nowait(item)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                self._classify_fn(item)
            except Exception:
                logger.exception(
                    "thread_classify worker: classify_fn raised; item dropped"
                )
            finally:
                self._queue.task_done()

    def join_queue(self, timeout: Optional[float] = None) -> None:
        """Test helper: block until every currently-queued item has been
        processed (or ``timeout`` elapses). Not used by production code."""
        self._queue.join()
