"""Unit tests for ``_sse_utils.to_jsonable``.

The handlers (run.py / review.py) pipe LangGraph events through
``to_jsonable`` before yielding to ``ctx.utils.sse``. If those events
still contain Pydantic models when ``json.dumps`` runs, the platform's
SSE helper falls back to ``str(data)`` and the frontend receives Python
repr instead of JSON — so the inbox tree never fills.

Run with::

    pytest agents/email/tests/test_sse_utils.py -v
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from _models import (
    Action,
    ClassifiedEmail,
    DraftItem,
    Email,
    ReviewDecision,
    UserRule,
)
from _sse_utils import to_jsonable


def _email(eid="m1") -> Email:
    return Email(
        id=eid,
        from_="alice@example.com",
        to=["me@example.com"],
        subject="Hi",
        body_text="hello",
        received_at=datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc),
        thread_id=f"thr_{eid}",
    )


# ─── Primitive passthrough ──────────────────────────────────────────────────


def test_passthrough_for_primitives():
    assert to_jsonable(None) is None
    assert to_jsonable("hi") == "hi"
    assert to_jsonable(42) == 42
    assert to_jsonable(3.14) == 3.14
    assert to_jsonable(True) is True


# ─── Pydantic models ────────────────────────────────────────────────────────


def test_email_becomes_dict_with_iso_datetime():
    out = to_jsonable(_email())
    assert isinstance(out, dict)
    # received_at should be an ISO string, not a datetime object
    assert isinstance(out["received_at"], str)
    assert "2026-05-20" in out["received_at"]
    # The whole thing must be JSON-safe
    json.dumps(out)


def test_classified_email_recurses_into_nested_email():
    ce = ClassifiedEmail(
        email=_email("m2"),
        category="urgent_customer",
        needs_reply=True,
        priority=95,
        reason="VIP",
    )
    out = to_jsonable(ce)
    assert out["category"] == "urgent_customer"
    assert isinstance(out["email"], dict)
    assert out["email"]["id"] == "m2"
    json.dumps(out)


def test_draft_item_round_trips():
    d = DraftItem(
        email_id="m3",
        to=["alice@x.com"],
        subject="Re: Hi",
        body="reply",
        tone="friendly_professional",
        confidence=0.8,
        rationale="",
    )
    out = to_jsonable(d)
    assert out["email_id"] == "m3"
    assert out["tone"] == "friendly_professional"
    json.dumps(out)


# ─── Containers ─────────────────────────────────────────────────────────────


def test_list_of_pydantic_models_recurses():
    rules = [
        UserRule(kind="vip_domain", value="acme.com"),
        UserRule(kind="auto_archive", value="news@x.io"),
    ]
    out = to_jsonable(rules)
    assert isinstance(out, list)
    assert all(isinstance(r, dict) for r in out)
    assert out[0]["kind"] == "vip_domain"
    json.dumps(out)


def test_dict_with_pydantic_values_recurses():
    payload = {
        "draft": DraftItem(
            email_id="m1", to=["x"], subject="s", body="b",
            tone="formal", confidence=0.5, rationale="",
        ),
        "decisions": [ReviewDecision(email_id="m1", action="approve")],
        "actions": [Action(email_id="m1", op="save_draft")],
    }
    out = to_jsonable(payload)
    assert isinstance(out["draft"], dict)
    assert isinstance(out["decisions"], list)
    assert out["decisions"][0]["action"] == "approve"
    assert out["actions"][0]["op"] == "save_draft"
    json.dumps(out)


def test_set_becomes_list():
    out = to_jsonable({"hello", "world"})
    assert isinstance(out, list)
    assert sorted(out) == ["hello", "world"]
    json.dumps(out)


def test_tuple_becomes_list():
    out = to_jsonable((1, 2, "three"))
    assert out == [1, 2, "three"]
    json.dumps(out)


# ─── Realistic LangGraph event shapes ───────────────────────────────────────


def test_langgraph_state_update_with_classified():
    """Mirrors the actual stream_mode='updates' payload from classify node."""
    event = {
        "classify": {
            "classified": [
                ClassifiedEmail(
                    email=_email("m1"),
                    category="urgent_customer",
                    needs_reply=True,
                    priority=95,
                    reason="VIP",
                ),
                ClassifiedEmail(
                    email=_email("m2"),
                    category="meeting",
                    needs_reply=True,
                    priority=70,
                    reason="ICS",
                ),
            ]
        }
    }
    out = to_jsonable(event)
    # The wire payload must be parseable as JSON (this is the actual
    # bug we're guarding against).
    wire = json.dumps(out)
    parsed = json.loads(wire)
    assert "classify" in parsed
    assert len(parsed["classify"]["classified"]) == 2
    assert parsed["classify"]["classified"][0]["category"] == "urgent_customer"
    assert parsed["classify"]["classified"][0]["email"]["id"] == "m1"


def test_langgraph_review_interrupt_payload():
    """The interrupt payload — frontend renders this as the DraftReviewCard."""
    payload = {
        "type": "human_review_required",
        "interrupt_id": "rev_m42",
        "email_id": "m42",
        "draft": DraftItem(
            email_id="m42",
            to=["alice@x.com"],
            subject="Re: budget",
            body="ok",
            tone="formal",
            confidence=0.9,
            rationale="",
        ).model_dump(mode="json"),  # node already pre-serializes
        "options": ["approve", "edit", "reject", "regenerate", "skip"],
        "remaining": 3,
    }
    out = to_jsonable(payload)
    json.dumps(out)
    # Idempotent: passing through to_jsonable again shouldn't break anything
    assert to_jsonable(out) == out


# ─── Fallback for surprises ─────────────────────────────────────────────────


class _Weird:
    def __repr__(self) -> str:
        return "<Weird object>"


def test_unknown_object_falls_back_to_str():
    out = to_jsonable(_Weird())
    assert isinstance(out, str)
    json.dumps(out)


def test_object_with_value_attr_recurses():
    """LangGraph's Interrupt object has a .value attribute carrying the payload."""

    class _FakeInterrupt:
        def __init__(self, value):
            self.value = value

    ce = ClassifiedEmail(
        email=_email(), category="internal",
        needs_reply=False, priority=20, reason="",
    )
    obj = _FakeInterrupt(ce)
    out = to_jsonable(obj)
    assert isinstance(out, dict)
    assert out["category"] == "internal"
    json.dumps(out)
