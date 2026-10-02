"""thread — HTTP backend for the composer.top ask-tracking strip.

One route: GET /asks?session_id=<id> — the active session's asks, flat
(parent nesting is resolved client-side from parent_id), ordered oldest
first so a child always renders after its parent has been seen.

Mounted at /api/plugins/thread/ by the dashboard plugin system (see
dashboard/manifest.json).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter

router = APIRouter()

# db.py lives at the plugin root (one level up from dashboard/).
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))
import db  # noqa: E402


def _row_to_dict(row: Any) -> dict:
    return {
        "id": row[0],
        "session_id": row[1],
        "parent_id": row[2],
        "title": row[3],
        "kind": row[4],
        "state": row[5],
        "reopened_count": row[6],
        "created_turn": row[7],
        "resolved_turn": row[8],
        "created_at": row[9],
        "updated_at": row[10],
    }


@router.get("/asks")
async def list_asks(session_id: str) -> dict:
    """Asks for ONE session only — no global counter, no cross-session leak."""
    con = db.connect()
    try:
        cur = con.execute(
            "SELECT id, session_id, parent_id, title, kind, state, reopened_count, "
            "created_turn, resolved_turn, created_at, updated_at "
            "FROM asks WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        )
        rows = [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        con.close()
    return {"asks": rows}
