import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db import SCHEMA, record_ask, current_ask_count  # noqa: E402


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
    count = con.execute("SELECT COUNT(*) FROM asks WHERE session_id = ?", ("s1",)).fetchone()[0]
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
