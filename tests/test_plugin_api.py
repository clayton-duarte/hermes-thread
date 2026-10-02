"""Tests for dashboard/plugin_api.py's /asks route.

Hermetic: a temp sqlite file via db.connect(db_path=...), monkeypatched
into the route by overriding db.default_db_path — no real ~/.hermes writes,
no network, no subprocess.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard"))

import plugin_api  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import db as db_module  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "thread.db")
    monkeypatch.setattr(db_module, "default_db_path", lambda: db_path)

    app = FastAPI()
    app.include_router(plugin_api.router)
    return TestClient(app)


def _seed(db_path_getter):
    con = db_module.connect()
    now = time.time()

    def insert(id_, session_id, parent_id, title, state, reopened_count=0):
        con.execute(
            "INSERT INTO asks (id, session_id, parent_id, title, kind, state, "
            "reopened_count, created_turn, resolved_turn, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, NULL, ?, ?, 't1', NULL, ?, ?)",
            (id_, session_id, parent_id, title, state, reopened_count, now, now),
        )

    insert("current-1", "s1", None, "current ask", "current")
    insert("open-1", "s1", None, "open ask", "open")
    insert("parent-1", "s1", None, "parent ask", "completed")
    insert("child-1", "s1", "parent-1", "child ask", "completed", reopened_count=2)
    con.commit()
    con.close()


def test_returns_correctly_shaped_json_for_seeded_db(client):
    _seed(None)

    resp = client.get("/asks", params={"session_id": "s1"})
    assert resp.status_code == 200
    body = resp.json()
    assert "asks" in body
    by_id = {a["id"]: a for a in body["asks"]}

    assert by_id["current-1"]["state"] == "current"
    assert by_id["open-1"]["state"] == "open"
    assert by_id["parent-1"]["state"] == "completed"

    child = by_id["child-1"]
    assert child["state"] == "completed"
    assert child["parent_id"] == "parent-1"
    assert child["reopened_count"] == 2


def test_zero_asks_session_returns_empty_list(client):
    resp = client.get("/asks", params={"session_id": "empty-session"})
    assert resp.status_code == 200
    assert resp.json() == {"asks": []}


def test_only_returns_the_requested_session(client):
    _seed(None)
    con = db_module.connect()
    con.execute(
        "INSERT INTO asks (id, session_id, parent_id, title, kind, state, "
        "reopened_count, created_turn, resolved_turn, created_at, updated_at) "
        "VALUES ('other-1', 's2', NULL, 'other session ask', NULL, 'current', "
        "0, 't1', NULL, 0, 0)"
    )
    con.commit()
    con.close()

    resp_s1 = client.get("/asks", params={"session_id": "s1"})
    ids_s1 = {a["id"] for a in resp_s1.json()["asks"]}
    assert "other-1" not in ids_s1
    assert ids_s1 == {"current-1", "open-1", "parent-1", "child-1"}

    resp_s2 = client.get("/asks", params={"session_id": "s2"})
    ids_s2 = {a["id"] for a in resp_s2.json()["asks"]}
    assert ids_s2 == {"other-1"}
