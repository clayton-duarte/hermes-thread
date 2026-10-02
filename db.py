"""thread.db schema + minimal ask-tracking operations.

Invariant enforced here (and unit-tested): at most one ask per session has
state='current'. seen_turns makes the capture hook idempotent — replaying the
same turn_id must never create a duplicate ask (or apply a transition twice).
"""

from __future__ import annotations

import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

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
    con = sqlite3.connect(path, check_same_thread=False)
    con.executescript(SCHEMA)
    con.commit()
    return con


def _claim_turn(con: sqlite3.Connection, *, session_id: str, turn_id: str) -> bool:
    """Insert (session_id, turn_id) into seen_turns. True the first time,
    False if already seen — caller must then no-op (idempotency)."""
    cur = con.execute(
        "SELECT 1 FROM seen_turns WHERE session_id = ? AND turn_id = ?",
        (session_id, turn_id),
    )
    if cur.fetchone() is not None:
        return False
    con.execute(
        "INSERT INTO seen_turns (session_id, turn_id) VALUES (?, ?)",
        (session_id, turn_id),
    )
    return True


def _demote_current(con: sqlite3.Connection, *, session_id: str, now: float) -> None:
    con.execute(
        "UPDATE asks SET state = 'open', updated_at = ? "
        "WHERE session_id = ? AND state = 'current'",
        (now, session_id),
    )


def record_ask(
    con: sqlite3.Connection,
    *,
    session_id: str,
    title: str,
    turn_id: str,
    kind: Optional[str] = None,
    parent_id: Optional[str] = None,
) -> Optional[str]:
    """Insert an ask for (session_id, turn_id) unless already seen (idempotent).

    Enforces the one-current-ask-per-session invariant: demotes any existing
    'current' ask in this session to 'open' before inserting the new one as
    'current'. Returns the new ask id, or None if turn_id was already seen.
    This is also the 'create' transition.
    """
    if not _claim_turn(con, session_id=session_id, turn_id=turn_id):
        return None  # already captured this turn — idempotent no-op

    now = time.time()
    ask_id = str(uuid.uuid4())
    if parent_id is not None and parent_id == ask_id:
        raise ValueError("parent_id must not reference its own ask id")
    _demote_current(con, session_id=session_id, now=now)
    con.execute(
        "INSERT INTO asks (id, session_id, parent_id, title, kind, state, "
        "reopened_count, created_turn, resolved_turn, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 'current', 0, ?, NULL, ?, ?)",
        (ask_id, session_id, parent_id, title, kind, turn_id, now, now),
    )
    con.commit()
    return ask_id


def current_ask_count(con: sqlite3.Connection, session_id: str) -> int:
    cur = con.execute(
        "SELECT COUNT(*) FROM asks WHERE session_id = ? AND state = 'current'",
        (session_id,),
    )
    return cur.fetchone()[0]


_SELECT_COLS = (
    "id, session_id, parent_id, title, kind, state, reopened_count, "
    "created_turn, resolved_turn, created_at, updated_at"
)
_ROW_KEYS = (
    "id",
    "session_id",
    "parent_id",
    "title",
    "kind",
    "state",
    "reopened_count",
    "created_turn",
    "resolved_turn",
    "created_at",
    "updated_at",
)


def _row_to_dict(row) -> Dict[str, Any]:
    return dict(zip(_ROW_KEYS, row))


def get_lists(con: sqlite3.Connection, session_id: str) -> Dict[str, Any]:
    """The 3-state view fed to the classifier prompt: current (dict or None),
    open (list of dicts), completed (list of dicts)."""
    cur = con.execute(
        f"SELECT {_SELECT_COLS} FROM asks WHERE session_id = ? AND state = 'current'",
        (session_id,),
    )
    row = cur.fetchone()
    current = _row_to_dict(row) if row else None

    cur = con.execute(
        f"SELECT {_SELECT_COLS} FROM asks WHERE session_id = ? AND state = 'open' "
        "ORDER BY updated_at DESC",
        (session_id,),
    )
    open_asks = [_row_to_dict(r) for r in cur.fetchall()]

    cur = con.execute(
        f"SELECT {_SELECT_COLS} FROM asks WHERE session_id = ? AND state = 'completed' "
        "ORDER BY updated_at DESC",
        (session_id,),
    )
    completed = [_row_to_dict(r) for r in cur.fetchall()]

    return {"current": current, "open": open_asks, "completed": completed}


def apply_attach(con: sqlite3.Connection, *, session_id: str, turn_id: str) -> bool:
    """Message attaches to the current ask — no asks-table row change beyond
    marking the turn seen. Returns True if applied, False if turn_id was
    already seen (idempotent no-op)."""
    if not _claim_turn(con, session_id=session_id, turn_id=turn_id):
        return False
    con.commit()
    return True


def apply_move_pointer(
    con: sqlite3.Connection,
    *,
    session_id: str,
    ask_id: str,
    turn_id: str,
) -> bool:
    """An existing OPEN ask becomes current; the previous current (if any)
    becomes open. Returns True if applied, False if turn_id already seen."""
    if not _claim_turn(con, session_id=session_id, turn_id=turn_id):
        return False
    now = time.time()
    _demote_current(con, session_id=session_id, now=now)
    con.execute(
        "UPDATE asks SET state = 'current', updated_at = ? "
        "WHERE id = ? AND session_id = ? AND state = 'open'",
        (now, ask_id, session_id),
    )
    con.commit()
    return True


def apply_complete(con: sqlite3.Connection, *, session_id: str, turn_id: str) -> bool:
    """The current ask (if any) moves to completed. Returns True if applied,
    False if turn_id already seen."""
    if not _claim_turn(con, session_id=session_id, turn_id=turn_id):
        return False
    now = time.time()
    con.execute(
        "UPDATE asks SET state = 'completed', resolved_turn = ?, updated_at = ? "
        "WHERE session_id = ? AND state = 'current'",
        (turn_id, now, session_id),
    )
    con.commit()
    return True


def apply_reopen(
    con: sqlite3.Connection,
    *,
    session_id: str,
    ask_id: str,
    turn_id: str,
) -> bool:
    """A COMPLETED ask becomes current again; reopened_count += 1. The
    previous current (if any) becomes open. Returns True if applied, False if
    turn_id already seen."""
    if not _claim_turn(con, session_id=session_id, turn_id=turn_id):
        return False
    now = time.time()
    _demote_current(con, session_id=session_id, now=now)
    con.execute(
        "UPDATE asks SET state = 'current', reopened_count = reopened_count + 1, "
        "updated_at = ? WHERE id = ? AND session_id = ? AND state = 'completed'",
        (now, ask_id, session_id),
    )
    con.commit()
    return True
