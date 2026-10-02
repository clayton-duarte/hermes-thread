"""Stage-1 deterministic noise filter: drops ~60% of raw user turns for free.

Stage 2 (aux-model classify, not here) runs only on survivors. Ported from the
spike at ~/.hermes/cache/scratch/askspike/extract.py — do not rewrite; keep
pure (str in, bool/str out) so it unit-tests with no DB and no model.
"""
import json
import re

NOISE_PREFIXES = (
    "[CONTEXT COMPACTION",
    "[OUT-OF-BAND USER MESSAGE",
    "[IMPORTANT: Background process",
    "[IMPORTANT: The user has invoked",
    "[ASYNC DELEGATION BATCH",
)
# kanban/gateway notification echoes arrive as user-role messages
NOTIFY_RE = re.compile(r"^[✔✖⏸⏱⚠]\s*\[")
# pure control/ack turns carry no ask
ACK = {"y", "yes", "yep", "ok", "okay", "no", "n", "tldr", "done", "merged", "approved",
       "go", "do it", "thanks", "ty", "nope", "sure", "k"}


def is_noise(text: str) -> tuple[bool, str]:
    t = (text or "").strip()
    if not t:
        return True, "empty"
    for p in NOISE_PREFIXES:
        if t.startswith(p):
            return True, "system-banner"
    if NOTIFY_RE.match(t):
        return True, "kanban-notification"
    bare = re.sub(r"[^a-z ]", "", t.lower()).strip()
    if bare in ACK:
        return True, "ack"
    if len(t) < 12 and "?" not in t:
        return True, "too-short"
    return False, ""


def unwrap_multimodal(text: str) -> str:
    """Multimodal turns are stored as a NUL-prefixed JSON parts array."""
    if not text.startswith("\x00json:"):
        return text
    try:
        parts = json.loads(text[len("\x00json:"):])
    except Exception:
        return text
    return "\n".join(
        p.get("text", "")
        for p in parts
        if isinstance(p, dict) and p.get("type") == "text"
    ).strip()


def strip_attachments(text: str) -> str:
    text = re.sub(r"@image:`[^`]*`", "", text)
    text = re.sub(r"^\[screenshot\]$", "", text, flags=re.M)
    return text.strip()
