"""Validation tests for ``review.py`` HITL resume handler.

Covers the request-body validation and missing-env failure modes. The full
resume flow (against a live graph + checkpointer) is exercised in
``test_hitl_resume.py::test_checkpoint_persists_after_pause_so_new_app_can_resume``
which uses the same ``Command(resume=...)`` mechanism that ``review.py`` calls.

Run with::

    pytest agents/email/tests/test_review_handler.py -v
"""
from __future__ import annotations

import asyncio
from typing import Any


# Import the handler module — names ``review`` and ``run`` clash with stdlib
# names, but importing as the module is fine (route files live in the
# tests' sys.path via conftest.py).
import review as review_module


# ─── Fake context infrastructure ────────────────────────────────────────────


class _Req:
    def __init__(self, body):
        self.body = body
        self.signal = None


class _StubStore:
    """Stand-in for ctx.store; only ``langgraph_checkpointer`` is touched."""

    def __init__(self):
        from langgraph.checkpoint.memory import InMemorySaver
        self.langgraph_checkpointer = InMemorySaver()


class _Ctx:
    def __init__(self, body, env=None, conversation_id="test-conv"):
        self.request = _Req(body)
        self.env = env or {}
        self.conversation_id = conversation_id
        self.kv = None
        self.store = _StubStore()


# ─── Validation tests ──────────────────────────────────────────────────────


def test_validate_body_rejects_unknown_decision():
    out = review_module._validate_body({"decision": "delete-everything"})
    assert isinstance(out, dict)
    assert out["status_code"] == 400
    assert "decision must be" in out["body"]["error"]


def test_validate_body_rejects_missing_decision():
    out = review_module._validate_body({})
    assert isinstance(out, dict)
    assert out["status_code"] == 400


def test_validate_body_rejects_edit_without_body():
    out = review_module._validate_body({"decision": "edit"})
    assert isinstance(out, dict)
    assert out["status_code"] == 400
    assert "edited_body" in out["body"]["error"]


def test_validate_body_rejects_edit_with_empty_body():
    out = review_module._validate_body({"decision": "edit", "edited_body": "   "})
    assert isinstance(out, dict)
    assert out["status_code"] == 400


def test_validate_body_accepts_edit_with_body():
    out = review_module._validate_body({
        "decision": "edit",
        "edited_body": "I rewrote this myself",
    })
    assert not isinstance(out, dict) or "status_code" not in out
    action, edited, feedback = out  # type: ignore[misc]
    assert action == "edit"
    assert edited == "I rewrote this myself"
    assert feedback is None


def test_validate_body_accepts_approve():
    action, edited, feedback = review_module._validate_body({"decision": "approve"})
    assert action == "approve"
    assert edited is None
    assert feedback is None


def test_validate_body_accepts_regenerate_with_feedback():
    action, edited, feedback = review_module._validate_body({
        "decision": "regenerate",
        "feedback": "tone too casual",
    })
    assert action == "regenerate"
    assert feedback == "tone too casual"


def test_validate_body_normalizes_case_and_whitespace():
    action, _, _ = review_module._validate_body({"decision": "  APPROVE  "})
    assert action == "approve"


# ─── Handler-level error paths ─────────────────────────────────────────────


def test_handler_returns_400_for_invalid_decision():
    ctx = _Ctx({"decision": "??"})
    out = asyncio.run(review_module.handler(ctx))
    assert out["status_code"] == 400


def test_handler_returns_400_for_edit_without_body():
    ctx = _Ctx({"decision": "edit"})
    out = asyncio.run(review_module.handler(ctx))
    assert out["status_code"] == 400


def test_handler_returns_500_on_missing_env():
    """Without AI_GATEWAY_* the LLM factory raises — handler returns 500."""
    ctx = _Ctx({"decision": "approve"}, env={})
    out = asyncio.run(review_module.handler(ctx))
    assert out["status_code"] == 500
    assert "AI_GATEWAY" in out["body"]["error"]


def test_handler_returns_500_on_partial_env():
    ctx = _Ctx(
        {"decision": "approve"},
        env={"AI_GATEWAY_API_KEY": "sk-test"},  # missing AI_GATEWAY_BASE_URL
    )
    out = asyncio.run(review_module.handler(ctx))
    assert out["status_code"] == 500


# ─── Body construction smoke ────────────────────────────────────────────────


def test_handler_does_not_crash_on_None_body():
    """Some platforms send {} or null for empty bodies — handler tolerates both."""
    ctx = _Ctx(None)
    out = asyncio.run(review_module.handler(ctx))
    # Empty body → no decision → 400
    assert out["status_code"] == 400
