"""thread — HTTP backend for the composer.top ask-tracking strip.

Routes:
  GET  /asks?session_id=<id>     — the active session's asks (see below).
  GET  /model-options            — providers + curated models for the
                                    thread_classify picker. Reuses
                                    hermes_cli.inventory (the same substrate as
                                    the Models page / kanban's own
                                    /model-options route) so it can't offer a
                                    provider/model pair Hermes would reject.
  GET  /thread-classify-config   — current auxiliary.thread_classify.* from
                                    config.yaml.
  PUT  /thread-classify-config   — write provider/model/reasoning_effort for
                                    thread_classify. Validates the pair against
                                    the same model-options catalog before
                                    writing; an unknown provider/model is
                                    rejected with 400, never silently written.

Mounted at /api/plugins/thread/ by the dashboard plugin system (see
dashboard/manifest.json). The desktop Settings -> Models page cannot show a
plugin's auxiliary task (it only knows the hardcoded built-in slots), so this
plugin ships its own picker against its own backend route instead of
POST /api/model/set, which 400s on any task name it doesn't recognise.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# db.py lives at the plugin root (one level up from dashboard/).
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))
import db  # noqa: E402

AUX_TASK = "thread_classify"


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


# ---------------------------------------------------------------------------
# thread_classify model picker
# ---------------------------------------------------------------------------


@router.get("/model-options")
def model_options() -> dict:
    """Providers + curated models for the thread_classify picker.

    Reuses hermes_cli.inventory.build_models_payload (the same read-only
    model-listing substrate the Models page and the kanban plugin use) instead
    of hardcoding a model list.
    """
    try:
        from hermes_cli.inventory import build_models_payload, load_picker_context

        payload = build_models_payload(
            load_picker_context(),
            explicit_only=True,
            canonical_order=True,
            probe_custom_providers=False,
        )
        return {
            "providers": [
                {
                    "slug": row.get("slug", ""),
                    "label": row.get("label") or row.get("slug", ""),
                    "models": list(row.get("models") or []),
                }
                for row in payload.get("providers", [])
                if row.get("models")
            ]
        }
    except Exception:
        # Empty catalog -> the UI falls back to a free-text input.
        return {"providers": []}


def _model_catalog() -> dict:
    """slug -> set(models) from /model-options, for validating a write."""
    catalog: dict = {}
    for row in model_options().get("providers", []):
        slug = str(row.get("slug", "")).strip().lower()
        if slug:
            catalog[slug] = {str(m) for m in row.get("models", [])}
    return catalog


@router.get("/thread-classify-config")
def get_thread_classify_config() -> dict:
    """Current auxiliary.thread_classify.* — provider/model/reasoning_effort."""
    from hermes_cli.config import load_config

    config = load_config() or {}
    aux = config.get("auxiliary") if isinstance(config, dict) else None
    slot = aux.get(AUX_TASK) if isinstance(aux, dict) else None
    slot = slot if isinstance(slot, dict) else {}
    return {
        "provider": slot.get("provider", "auto"),
        "model": slot.get("model", ""),
        "reasoning_effort": slot.get("reasoning_effort"),
    }


class ThreadClassifyConfigBody(BaseModel):
    provider: str
    model: str
    reasoning_effort: Optional[str] = None


@router.put("/thread-classify-config")
def set_thread_classify_config(body: ThreadClassifyConfigBody) -> dict:
    """Write auxiliary.thread_classify.{provider,model,reasoning_effort}.

    Validates provider/model against the same catalog /model-options serves
    before writing — an unknown pair is rejected with 400, never silently
    written. ``provider="auto"`` always validates (deferred to runtime
    auto-selection, same semantics as the built-in aux slots).
    """
    provider = (body.provider or "").strip()
    model = (body.model or "").strip()
    if not provider:
        raise HTTPException(status_code=400, detail="provider is required")

    if provider.lower() != "auto":
        catalog = _model_catalog()
        models_for_provider = catalog.get(provider.lower())
        if models_for_provider is None:
            raise HTTPException(status_code=400, detail=f"unknown provider: {provider}")
        if model and model not in models_for_provider:
            raise HTTPException(
                status_code=400,
                detail=f"unknown model {model!r} for provider {provider!r}",
            )

    from hermes_cli.config import load_config, save_config

    config = load_config() or {}
    aux = config.get("auxiliary")
    if not isinstance(aux, dict):
        aux = {}
    slot = aux.get(AUX_TASK)
    slot = dict(slot) if isinstance(slot, dict) else {}
    slot["provider"] = provider
    slot["model"] = model
    if body.reasoning_effort is not None:
        slot["reasoning_effort"] = body.reasoning_effort
    else:
        slot.pop("reasoning_effort", None)
    aux[AUX_TASK] = slot
    config["auxiliary"] = aux
    save_config(config)

    return {
        "ok": True,
        "provider": provider,
        "model": model,
        "reasoning_effort": slot.get("reasoning_effort"),
    }
