import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from db import SCHEMA, current_ask_count, record_ask  # noqa: E402


def fresh_con() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    return con


def test_schema_creates_asks_and_seen_turns_tables():
    con = fresh_con()
    tables = {
        row[0]
        for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"asks", "seen_turns"} <= tables


def test_record_ask_creates_current_ask():
    con = fresh_con()
    ask_id = record_ask(con, session_id="s1", title="add retries", turn_id="t1")
    assert ask_id is not None
    row = con.execute("SELECT state FROM asks WHERE id = ?", (ask_id,)).fetchone()
    assert row[0] == "current"


def test_replaying_same_turn_id_creates_one_ask():
    con = fresh_con()
    first = record_ask(con, session_id="s1", title="add retries", turn_id="t1")
    second = record_ask(con, session_id="s1", title="add retries (dup)", turn_id="t1")
    assert first is not None
    assert second is None  # idempotent no-op on replay
    count = con.execute(
        "SELECT COUNT(*) FROM asks WHERE session_id = ?", ("s1",)
    ).fetchone()[0]
    assert count == 1


def test_at_most_one_current_ask_per_session():
    con = fresh_con()
    record_ask(con, session_id="s1", title="first ask", turn_id="t1")
    record_ask(con, session_id="s1", title="second ask", turn_id="t2")
    assert current_ask_count(con, "s1") == 1


def test_current_asks_are_isolated_per_session():
    con = fresh_con()
    record_ask(con, session_id="s1", title="ask a", turn_id="t1")
    record_ask(con, session_id="s2", title="ask b", turn_id="t1")
    assert current_ask_count(con, "s1") == 1
    assert current_ask_count(con, "s2") == 1


def test_record_ask_rejects_parent_id_equal_to_its_own_generated_id():
    # Defence in depth: the renderer tolerates a self-parent, but the DB
    # must reject one on write even if a caller manages to collide ids
    # (e.g. a replayed/forced uuid) — the classifier writes parent_id from
    # LLM output with no cycle guard today, so this must hold unconditionally.
    con = fresh_con()
    forced_id = "11111111-1111-1111-1111-111111111111"
    with monkeypatch_uuid(forced_id):
        with pytest.raises(ValueError):
            record_ask(
                con, session_id="s1", title="self", turn_id="t1", parent_id=forced_id
            )


class monkeypatch_uuid:
    """Minimal context manager forcing db.uuid.uuid4() to a fixed value."""

    def __init__(self, forced_id):
        self.forced_id = forced_id

    def __enter__(self):
        import db as db_module

        class _Fixed:
            def __init__(self, hex_str):
                self._hex = hex_str

            def __str__(self):
                return self._hex

        self._orig = db_module.uuid.uuid4
        db_module.uuid.uuid4 = lambda: _Fixed(self.forced_id)
        return self

    def __exit__(self, *exc):
        import db as db_module

        db_module.uuid.uuid4 = self._orig
