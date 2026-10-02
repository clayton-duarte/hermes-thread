"""Unit tests for the five classify transitions (model mocked) and the
one-current-ask invariant, plus the fail-open contract on classifier error.
"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db  # noqa: E402
from classify import classify_and_apply  # noqa: E402


def fresh_con() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript(db.SCHEMA)
    return con


def fake_llm(parsed):
    result = MagicMock()
    result.parsed = parsed
    return MagicMock(return_value=result)


def test_attach_keeps_current_ask_unchanged():
    con = fresh_con()
    db.record_ask(con, session_id="s1", title="add retries", turn_id="t1")
    llm = fake_llm({"transition": "attach"})

    classify_and_apply(
        con, llm, session_id="s1", turn_id="t2", message="also handle timeouts"
    )

    lists = db.get_lists(con, "s1")
    assert lists["current"]["title"] == "add retries"
    assert db.current_ask_count(con, "s1") == 1


def test_create_makes_new_current_and_demotes_old_to_open():
    con = fresh_con()
    db.record_ask(con, session_id="s1", title="add retries", turn_id="t1")
    llm = fake_llm({"transition": "create", "title": "new feature: dark mode"})

    classify_and_apply(
        con, llm, session_id="s1", turn_id="t2", message="lets now work on dark mode"
    )

    lists = db.get_lists(con, "s1")
    assert lists["current"]["title"] == "new feature: dark mode"
    assert [a["title"] for a in lists["open"]] == ["add retries"]
    assert db.current_ask_count(con, "s1") == 1


def test_move_pointer_promotes_open_ask_to_current():
    con = fresh_con()
    first_id = db.record_ask(con, session_id="s1", title="add retries", turn_id="t1")
    db.record_ask(con, session_id="s1", title="dark mode", turn_id="t2")
    llm = fake_llm({"transition": "move_pointer", "ask_id": first_id})

    classify_and_apply(
        con, llm, session_id="s1", turn_id="t3", message="back to the retries thing"
    )

    lists = db.get_lists(con, "s1")
    assert lists["current"]["id"] == first_id
    assert [a["title"] for a in lists["open"]] == ["dark mode"]
    assert db.current_ask_count(con, "s1") == 1


def test_complete_moves_current_to_completed():
    con = fresh_con()
    db.record_ask(con, session_id="s1", title="add retries", turn_id="t1")
    llm = fake_llm({"transition": "complete"})

    classify_and_apply(
        con, llm, session_id="s1", turn_id="t2", message="confirm it's done"
    )

    lists = db.get_lists(con, "s1")
    assert lists["current"] is None
    assert [a["title"] for a in lists["completed"]] == ["add retries"]
    assert db.current_ask_count(con, "s1") == 0


def test_reopen_promotes_completed_ask_and_bumps_reopened_count():
    con = fresh_con()
    ask_id = db.record_ask(con, session_id="s1", title="add retries", turn_id="t1")
    db.apply_complete(con, session_id="s1", turn_id="t2")
    llm = fake_llm({"transition": "reopen", "ask_id": ask_id})

    classify_and_apply(
        con,
        llm,
        session_id="s1",
        turn_id="t3",
        message="reopen the retries ask, found a bug",
    )

    lists = db.get_lists(con, "s1")
    assert lists["current"]["id"] == ask_id
    assert lists["current"]["reopened_count"] == 1
    assert db.current_ask_count(con, "s1") == 1


def test_classifier_exception_leaves_db_untouched_and_never_raises():
    con = fresh_con()
    db.record_ask(con, session_id="s1", title="add retries", turn_id="t1")
    before = db.get_lists(con, "s1")

    def boom(**kwargs):
        raise RuntimeError("model is down")

    classify_and_apply(con, boom, session_id="s1", turn_id="t2", message="whatever")

    after = db.get_lists(con, "s1")
    assert after == before


def test_malformed_classifier_result_leaves_db_untouched():
    con = fresh_con()
    db.record_ask(con, session_id="s1", title="add retries", turn_id="t1")
    before = db.get_lists(con, "s1")
    llm = fake_llm({"not": "a valid shape"})

    classify_and_apply(con, llm, session_id="s1", turn_id="t2", message="whatever")

    after = db.get_lists(con, "s1")
    assert after == before
