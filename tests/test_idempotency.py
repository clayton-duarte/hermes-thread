"""End-to-end idempotency: replaying the same turn_id through the hook +
worker pipeline must create exactly one ask, never two.
"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db  # noqa: E402
from classify import classify_and_apply  # noqa: E402
from worker import ThreadWorker  # noqa: E402


def fresh_con() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:", check_same_thread=False)
    con.executescript(db.SCHEMA)
    return con


def test_replaying_same_turn_id_through_worker_creates_one_ask():
    con = fresh_con()
    result = MagicMock()
    result.parsed = {"transition": "create", "title": "add retries"}
    llm = MagicMock(return_value=result)

    worker = ThreadWorker(
        lambda item: classify_and_apply(
            con,
            llm,
            session_id=item["session_id"],
            turn_id=item["turn_id"],
            message=item["message"],
        )
    )

    item = {"session_id": "s1", "turn_id": "t1", "message": "please add retries"}
    worker.enqueue(item)
    worker.enqueue(dict(item))  # exact replay of the same turn_id
    worker.join_queue()

    count = con.execute(
        "SELECT COUNT(*) FROM asks WHERE session_id = ?", ("s1",)
    ).fetchone()[0]
    assert count == 1
