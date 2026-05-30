"""HITL pause + resume tests for the ``review`` node.

Exercises ``langgraph.types.interrupt`` and ``Command(resume=...)`` against
an in-memory checkpointer using a minimal one-node graph (just ``review``).
This isolates the HITL machinery from the full pipeline so the tests are
fast and don't need fake LLMs.

Companion to test_graph.py's auto-approve test (which covers the cron path).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from _models import DraftItem, ReviewDecision
from _nodes import review
from _state import EmailAssistantState


def _draft(email_id: str = "m1", body: str = "draft body") -> DraftItem:
    return DraftItem(
        email_id=email_id,
        to=["alice@x.com"],
        subject="Re: Hi",
        body=body,
        tone="friendly_professional",
        confidence=0.8,
        rationale="",
    )


def _build_review_only_graph():
    """Tiny graph that goes START → review → END.

    Lets us exercise the interrupt() pause + resume cycle without a fake LLM
    or fake provider. The state schema is the real ``EmailAssistantState``.
    """
    g = StateGraph(EmailAssistantState)
    g.add_node("review", review)
    g.add_edge(START, "review")
    g.add_edge("review", END)
    return g.compile(checkpointer=InMemorySaver())


# ─── Pause behavior ─────────────────────────────────────────────────────────


def test_review_pauses_at_interrupt_in_human_path():
    """Without ``auto_approve``, review() raises GraphInterrupt → ``__interrupt__``
    appears in the stream and the graph state is checkpointed mid-node."""
    app = _build_review_only_graph()
    config = {"configurable": {"thread_id": "t-pause-1"}}

    async def _run():
        events = []
        async for event in app.astream(
            {"pending_review": _draft("m1"), "auto_approve": False},
            config=config,
            stream_mode="updates",
        ):
            events.append(event)
        return events

    events = asyncio.run(_run())
    # The stream should contain at least one __interrupt__ event
    interrupt_events = [e for e in events if "__interrupt__" in e]
    assert interrupt_events, f"expected __interrupt__ in stream, got: {events}"


def test_interrupt_payload_has_expected_shape():
    """The payload sent to the frontend matches the SSE contract spec."""
    app = _build_review_only_graph()
    config = {"configurable": {"thread_id": "t-payload-1"}}

    async def _run():
        async for event in app.astream(
            {"pending_review": _draft("m1"), "auto_approve": False,
             "prioritized": [_draft("m1"), _draft("m2"), _draft("m3")],
             "cursor": 0},
            config=config,
            stream_mode="updates",
        ):
            if "__interrupt__" in event:
                return event["__interrupt__"]
        return None

    interrupts = asyncio.run(_run())
    assert interrupts, "no interrupt was raised"
    # LangGraph wraps the value in an Interrupt object with .value
    payload = interrupts[0].value if hasattr(interrupts[0], "value") else interrupts[0]
    assert payload["type"] == "human_review_required"
    assert payload["email_id"] == "m1"
    assert payload["interrupt_id"] == "rev_m1"
    assert "draft" in payload
    assert payload["draft"]["email_id"] == "m1"
    assert payload["options"] == ["approve", "edit", "reject", "regenerate", "skip"]
    # cursor=0, len=3 → remaining = 3 - 0 - 1 = 2
    assert payload["remaining"] == 2


# ─── Resume behavior ────────────────────────────────────────────────────────


def _pause_then_resume(thread_id: str, resume_value):
    """Helper: start the graph (pauses), then resume with the given value.

    Returns the final state snapshot's values dict.
    """
    app = _build_review_only_graph()
    config = {"configurable": {"thread_id": thread_id}}

    async def _go():
        # First call — pause
        async for _ in app.astream(
            {"pending_review": _draft("m1"), "auto_approve": False},
            config=config,
            stream_mode="updates",
        ):
            pass
        # Second call — resume with the value
        async for _ in app.astream(
            Command(resume=resume_value),
            config=config,
            stream_mode="updates",
        ):
            pass
        snap = await app.aget_state(config)
        return snap.values

    return asyncio.run(_go())


def test_resume_with_approve_records_decision():
    values = _pause_then_resume("t-approve", {"action": "approve"})
    decisions = values.get("review_decisions") or []
    assert len(decisions) == 1
    assert decisions[0].action == "approve"
    assert decisions[0].email_id == "m1"
    assert decisions[0].edited_body is None


def test_resume_with_edit_carries_edited_body():
    values = _pause_then_resume(
        "t-edit",
        {"action": "edit", "edited_body": "I rewrote this myself"},
    )
    decisions = values.get("review_decisions") or []
    assert len(decisions) == 1
    assert decisions[0].action == "edit"
    assert decisions[0].edited_body == "I rewrote this myself"


def test_resume_with_regenerate_carries_feedback():
    values = _pause_then_resume(
        "t-regenerate",
        {"action": "regenerate", "feedback": "tone too casual; make it formal"},
    )
    decisions = values.get("review_decisions") or []
    assert len(decisions) == 1
    assert decisions[0].action == "regenerate"
    assert decisions[0].feedback == "tone too casual; make it formal"


def test_resume_with_reject_records_decision():
    values = _pause_then_resume("t-reject", {"action": "reject"})
    decisions = values.get("review_decisions") or []
    assert decisions[0].action == "reject"


def test_resume_with_skip_records_decision():
    values = _pause_then_resume("t-skip", {"action": "skip"})
    decisions = values.get("review_decisions") or []
    assert decisions[0].action == "skip"


# ─── Defensive resume handling ──────────────────────────────────────────────


def test_resume_with_invalid_action_falls_back_to_approve():
    """A bogus action string from a misbehaving client → defensive approve."""
    values = _pause_then_resume("t-bogus", {"action": "delete-everything"})
    decisions = values.get("review_decisions") or []
    assert decisions[0].action == "approve"


def test_resume_with_non_dict_falls_back_to_approve():
    """Resume value isn't a dict at all (e.g. plain string) → approve."""
    values = _pause_then_resume("t-string", "approve")
    decisions = values.get("review_decisions") or []
    assert decisions[0].action == "approve"


# ─── Auto-approve path doesn't pause ────────────────────────────────────────


def test_auto_approve_path_completes_without_interrupt():
    """``auto_approve=True`` skips interrupt() and finishes in one invocation."""
    app = _build_review_only_graph()
    config = {"configurable": {"thread_id": "t-auto"}}

    async def _run():
        events = []
        async for event in app.astream(
            {"pending_review": _draft("m1"), "auto_approve": True},
            config=config,
            stream_mode="updates",
        ):
            events.append(event)
        snap = await app.aget_state(config)
        return events, snap.values

    events, values = asyncio.run(_run())
    # No interrupt should appear
    assert not any("__interrupt__" in e for e in events)
    # Decision was recorded
    decisions = values.get("review_decisions") or []
    assert len(decisions) == 1
    assert decisions[0].action == "approve"


# ─── Checkpoint persistence across "session boundary" ───────────────────────


def test_checkpoint_persists_after_pause_so_new_app_can_resume():
    """Simulates the platform's behavior: run.py pauses, the SSE response
    closes, then later review.py builds a fresh ``app`` (same checkpointer)
    and calls ``Command(resume=...)``. The state must rehydrate from
    checkpoint, not be lost."""
    saver = InMemorySaver()
    config = {"configurable": {"thread_id": "t-cross-session"}}

    async def _go():
        # First "session": run.py builds graph, pauses
        g1 = StateGraph(EmailAssistantState)
        g1.add_node("review", review)
        g1.add_edge(START, "review")
        g1.add_edge("review", END)
        app1 = g1.compile(checkpointer=saver)
        async for _ in app1.astream(
            {"pending_review": _draft("m42"), "auto_approve": False},
            config=config,
            stream_mode="updates",
        ):
            pass
        # First app instance is now garbage-collectable; build a fresh one
        # against the SAME checkpointer (mirrors what review.py does).
        g2 = StateGraph(EmailAssistantState)
        g2.add_node("review", review)
        g2.add_edge(START, "review")
        g2.add_edge("review", END)
        app2 = g2.compile(checkpointer=saver)
        async for _ in app2.astream(
            Command(resume={"action": "approve"}),
            config=config,
            stream_mode="updates",
        ):
            pass
        snap = await app2.aget_state(config)
        return snap.values

    values = asyncio.run(_go())
    decisions = values.get("review_decisions") or []
    # Same email id from the original "session" must be remembered
    assert len(decisions) == 1
    assert decisions[0].email_id == "m42"
    assert decisions[0].action == "approve"
