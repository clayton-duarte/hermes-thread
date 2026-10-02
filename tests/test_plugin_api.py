"""Hermetic tests for dashboard/plugin_api.py — /asks plus the thread_classify picker.

Nothing here touches the real ~/.hermes: the ask routes run against a temp sqlite
file (db.default_db_path monkeypatched to tmp_path), and the picker routes run
against an in-memory stand-in for hermes_cli.config installed via sys.modules, so
load_config/save_config can never reach the user's live config.yaml.
"""

from __future__ import annotations

import sys
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard"))

import plugin_api  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import db as db_module  # noqa: E402

# ---------------------------------------------------------------------------
# GET /asks — session-scoped ask list (card 3)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# thread_classify model picker (card 4)
# ---------------------------------------------------------------------------


class _FakeConfigStore:
    """In-memory stand-in for hermes_cli.config.load_config/save_config."""

    def __init__(self, initial: dict):
        self._data = initial

    def load_config(self):
        import copy

        return copy.deepcopy(self._data)

    def save_config(self, data):
        self._data = data


@pytest.fixture
def fake_config(monkeypatch):
    store = _FakeConfigStore({"auxiliary": {}})
    fake_module = types.ModuleType("hermes_cli.config")
    fake_module.load_config = store.load_config
    fake_module.save_config = store.save_config
    fake_hermes_cli = types.ModuleType("hermes_cli")
    fake_hermes_cli.config = fake_module
    monkeypatch.setitem(sys.modules, "hermes_cli", fake_hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", fake_module)
    return store


@pytest.fixture
def fake_inventory(monkeypatch):
    """Stub hermes_cli.inventory so model-options returns a known, small catalog."""
    fake_module = types.ModuleType("hermes_cli.inventory")

    def build_models_payload(ctx, **kwargs):
        return {
            "providers": [
                {
                    "slug": "openrouter",
                    "label": "OpenRouter",
                    "models": ["openai/gpt-4o-mini", "anthropic/claude-haiku"],
                },
                {"slug": "nous", "label": "Nous", "models": ["Hermes-4-70B"]},
            ]
        }

    def load_picker_context():
        return {}

    fake_module.build_models_payload = build_models_payload
    fake_module.load_picker_context = load_picker_context
    monkeypatch.setitem(sys.modules, "hermes_cli.inventory", fake_module)
    return fake_module


@pytest.fixture
def picker_client(fake_config, fake_inventory):
    import importlib

    importlib.reload(plugin_api)
    app = FastAPI()
    app.include_router(plugin_api.router)
    return TestClient(app)


def test_get_thread_classify_config_defaults_when_unset(picker_client):
    resp = picker_client.get("/thread-classify-config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "auto"
    assert body["model"] == ""


def test_model_options_lists_providers_from_inventory(picker_client):
    resp = picker_client.get("/model-options")
    assert resp.status_code == 200
    slugs = {p["slug"] for p in resp.json()["providers"]}
    assert slugs == {"openrouter", "nous"}


def test_put_thread_classify_config_round_trips(picker_client, fake_config):
    resp = picker_client.put(
        "/thread-classify-config",
        json={
            "provider": "openrouter",
            "model": "openai/gpt-4o-mini",
            "reasoning_effort": None,
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "provider": "openrouter",
        "model": "openai/gpt-4o-mini",
        "reasoning_effort": None,
    }

    # Round-trip: config.yaml (faked) now reflects the write.
    stored = fake_config.load_config()
    assert stored["auxiliary"]["thread_classify"]["provider"] == "openrouter"
    assert stored["auxiliary"]["thread_classify"]["model"] == "openai/gpt-4o-mini"

    # And GET reflects it too.
    resp = picker_client.get("/thread-classify-config")
    assert resp.json()["provider"] == "openrouter"
    assert resp.json()["model"] == "openai/gpt-4o-mini"


def test_put_thread_classify_config_rejects_unknown_model(picker_client, fake_config):
    resp = picker_client.put(
        "/thread-classify-config",
        json={"provider": "openrouter", "model": "totally-made-up-model"},
    )
    assert resp.status_code == 400
    assert "unknown model" in resp.json()["detail"]
    # Rejected write must not have landed.
    stored = fake_config.load_config()
    assert stored.get("auxiliary", {}).get("thread_classify") in (None, {})


def test_put_thread_classify_config_rejects_unknown_provider(
    picker_client, fake_config
):
    resp = picker_client.put(
        "/thread-classify-config",
        json={"provider": "not-a-real-provider", "model": "whatever"},
    )
    assert resp.status_code == 400
    assert "unknown provider" in resp.json()["detail"]


def test_put_thread_classify_config_allows_auto_provider(picker_client, fake_config):
    resp = picker_client.put(
        "/thread-classify-config", json={"provider": "auto", "model": ""}
    )
    assert resp.status_code == 200
    stored = fake_config.load_config()
    assert stored["auxiliary"]["thread_classify"]["provider"] == "auto"
