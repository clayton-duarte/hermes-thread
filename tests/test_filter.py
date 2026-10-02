import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from filter import is_noise, strip_attachments, unwrap_multimodal  # noqa: E402


def test_drops_system_banner():
    noise, why = is_noise("[CONTEXT COMPACTION] summary follows")
    assert noise is True
    assert why == "system-banner"


def test_drops_kanban_notification():
    noise, why = is_noise("✔ [card done]")
    assert noise is True
    assert why == "kanban-notification"


def test_drops_exact_ack():
    noise, why = is_noise("ok")
    assert noise is True
    assert why == "ack"


def test_drops_too_short_without_question():
    noise, why = is_noise("fix it now")
    assert noise is True
    assert why == "too-short"


def test_keeps_real_ask():
    noise, why = is_noise("Can you add retry logic to the upload handler?")
    assert noise is False
    assert why == ""


def test_keeps_empty_string_as_noise():
    noise, why = is_noise("")
    assert noise is True
    assert why == "empty"


def test_unwrap_multimodal_handles_nul_prefixed_json():
    raw = '\x00json:[{"type":"text","text":"hello"},{"type":"image","text":"ignored"}]'
    assert unwrap_multimodal(raw) == "hello"


def test_unwrap_multimodal_passthrough_for_plain_text():
    assert unwrap_multimodal("plain text") == "plain text"


def test_unwrap_multimodal_malformed_json_passthrough():
    raw = "\x00json:not valid json"
    assert unwrap_multimodal(raw) == raw


def test_strip_attachments_removes_image_markers_and_screenshot_lines():
    raw = "look at this @image:`abc123`\n[screenshot]\nwhat do you think?"
    result = strip_attachments(raw)
    assert "@image:" not in result
    assert "[screenshot]" not in result
    assert "what do you think?" in result
