"""thread.db schema + minimal ask-tracking operations.

Invariant enforced here (and unit-tested): at most one ask per session has
state='current'. seen_turns makes the capture hook idempotent — replaying the
same turn_id must never create a duplicate ask.
"""
from __future__ import annotations

import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS asks (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  parent_id TEXT,
  title TEXT NOT NULL,
  kind TEXT,
  state TEXT NOT NULL,
  reopened_count INTEGER NOT NULL DEFAULT 0,
  created_turn TEXT,
  resolved_turn TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS asks_session ON asks(session_id, state);
CREATE TABLE IF NOT EXISTS seen_turns (
  session_id TEXT,
  turn_id TEXT,
  PRIMARY KEY (session_id, turn_id)
);
"""


def default_db_path() -> str:
    home = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
    return str(Path(home) / "thread.db")


def connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or default_db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.commit()
    return con


def record_ask(
    con: sqlite3.Connection, *, session_id: str, title: str, turn_id: str,
    kind: Optional[str] = None, parent_id: Optional[str] = None,
) -> Optional[str]:
    """Insert an ask for (session_id, turn_id) unless already seen (idempotent).

    Enforces the one-current-ask-per-session invariant: demotes any existing
    'current' ask in this session to 'open' before inserting the new one as
    'current'. Returns the new ask id, or None if turn_id was already seen.
    """
    cur = con.execute(
        "SELECT 1 FROM seen_turns WHERE session_id = ? AND turn_id = ?",
        (session_id, turn_id),
    )
    if cur.fetchone() is not None:
        return None  # already captured this turn — idempotent no-op

    now = time.time()
    ask_id = str(uuid.uuid4())
    con.execute(
        "UPDATE asks SET state = 'open', updated_at = ? "
        "WHERE session_id = ? AND state = 'current'",
        (now, session_id),
    )
    con.execute(
        "INSERT INTO asks (id, session_id, parent_id, title, kind, state, "
        "reopened_count, created_turn, resolved_turn, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 'current', 0, ?, NULL, ?, ?)",
        (ask_id, session_id, parent_id, title, kind, turn_id, now, now),
    )
    con.execute(
        "INSERT INTO seen_turns (session_id, turn_id) VALUES (?, ?)",
        (session_id, turn_id),
    )
    con.commit()
    return ask_id


def current_ask_count(con: sqlite3.Connection, session_id: str) -> int:
    cur = con.execute(
        "SELECT COUNT(*) FROM asks WHERE session_id = ? AND state = 'current'",
        (session_id,),
    )
    return cur.fetchone()[0]
