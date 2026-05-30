"""Unit tests for the LangGraph nodes (fetch / classify / prioritize).

The classify node's LLM call is mocked via ``FakeOpenAIClient`` so tests
run offline. fetch / prioritize are pure-Python and test directly.

Run with::

    pytest agents/email/tests/test_nodes.py -v
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import pytest

from _models import ClassifiedEmail, Email, UserRule, UserRulesBundle
from _nodes import (
    _bundle_from_rules,
    _matches_auto_archive,
    _matches_vip_domain,
    classify,
    fetch,
    prioritize,
)


# ─── Test helpers ───────────────────────────────────────────────────────────


def _make_email(
    *,
    eid: str = "m1",
    sender: str = "alice@example.com",
    subject: str = "Test",
    body: str = "Hi there",
    has_ics: bool = False,
    received_at: datetime | None = None,
) -> Email:
    return Email(
        id=eid,
        from_=sender,
        to=["me@example.com"],
        subject=subject,
        body_text=body,
        received_at=received_at or datetime(2026, 5, 19, 10, 0, tzinfo=timezone.utc),
        thread_id=f"thr_{eid}",
        has_ics=has_ics,
    )


class FakeProvider:
    """Provider stub that returns a fixed inbox and records archive calls."""

    def __init__(self, inbox: list[Email]):
        self.inbox = inbox
        self.archived: list[str] = []
        self.read: list[str] = []

    async def fetch_inbox(self, since=None, limit=50):
        return list(self.inbox)

    async def archive(self, email_id: str) -> None:
        self.archived.append(email_id)

    async def mark_read(self, email_id: str) -> None:
        self.read.append(email_id)

    async def save_draft(self, draft) -> str:
        return "draft_test_xxx"

    async def load_user_rules(self) -> UserRulesBundle:
        return UserRulesBundle()


class FakeChoice:
    def __init__(self, content: str):
        self.message = type("M", (), {"content": content})()


class FakeChatResp:
    def __init__(self, content: str):
        self.choices = [FakeChoice(content)]


class FakeChatCompletions:
    def __init__(self, response_text: str | Exception):
        self.response_text = response_text
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs) -> FakeChatResp:
        self.calls.append(kwargs)
        if isinstance(self.response_text, Exception):
            raise self.response_text
        return FakeChatResp(self.response_text)


class FakeChat:
    def __init__(self, response_text: str | Exception):
        self.completions = FakeChatCompletions(response_text)


class FakeOpenAIClient:
    def __init__(self, response_text: str | Exception):
        self.chat = FakeChat(response_text)


# ─── helpers tests ──────────────────────────────────────────────────────────


def test_bundle_from_rules_aggregates():
    rules = [
        UserRule(kind="vip_domain", value="acme.com"),
        UserRule(kind="vip_domain", value="big.co"),
        UserRule(kind="auto_archive", value="news@x.io"),
        UserRule(kind="default_tone", value="formal"),
        UserRule(kind="signature", value="-- Me"),
        UserRule(kind="language", value="en"),
    ]
    bundle = _bundle_from_rules(rules)
    assert bundle.vip_domains == ["acme.com", "big.co"]
    assert bundle.auto_archive == ["news@x.io"]
    assert bundle.default_tone == "formal"
    assert bundle.signature == "-- Me"
    assert bundle.language == "en"


def test_matches_auto_archive_substring():
    e = _make_email(sender="ToolIO Newsletter <news@tool.io>")
    assert _matches_auto_archive(e, ["news@tool.io"]) is True
    assert _matches_auto_archive(e, ["other.com"]) is False
    assert _matches_auto_archive(e, []) is False


def test_matches_vip_domain():
    e = _make_email(sender="CEO <ceo@vipcustomer.com>")
    assert _matches_vip_domain(e, ["vipcustomer.com"]) is True
    assert _matches_vip_domain(e, ["other.com"]) is False


# ─── fetch ──────────────────────────────────────────────────────────────────


def test_fetch_keeps_normal_and_archives_matching():
    inbox = [
        _make_email(eid="m1", sender="alice@biz.com", subject="Real"),
        _make_email(eid="m2", sender="news@tool.io", subject="Promo"),
        _make_email(eid="m3", sender="bob@partner.com", subject="Hi"),
    ]
    provider = FakeProvider(inbox)
    state = {
        "user_rules": [UserRule(kind="auto_archive", value="news@tool.io")],
    }
    result = asyncio.run(fetch(state, provider=provider))
    kept_ids = [e.id for e in result["inbox"]]
    assert kept_ids == ["m1", "m3"]
    assert provider.archived == ["m2"]


def test_fetch_no_rules_keeps_all():
    inbox = [_make_email(eid="m1"), _make_email(eid="m2")]
    provider = FakeProvider(inbox)
    state: dict = {"user_rules": []}
    result = asyncio.run(fetch(state, provider=provider))
    assert len(result["inbox"]) == 2
    assert provider.archived == []


def test_fetch_archive_failure_does_not_crash():
    class FailingProvider(FakeProvider):
        async def archive(self, email_id):
            raise RuntimeError("nope")

    inbox = [_make_email(eid="m1", sender="news@tool.io")]
    provider = FailingProvider(inbox)
    state: dict = {"user_rules": [UserRule(kind="auto_archive", value="news@tool.io")]}
    result = asyncio.run(fetch(state, provider=provider))
    # Email is still dropped from inbox (we tried to archive)
    assert result["inbox"] == []


def test_fetch_short_circuits_when_classified_preloaded():
    """Caller pre-loaded classified (cache hint from frontend) → fetch
    should NOT call the provider; ``inbox`` is rebuilt from the pre-loaded
    classified entries so downstream summarize counts stay correct."""
    pre = [
        ClassifiedEmail(
            email=_make_email(eid="cached-1"),
            category="internal", needs_reply=False, priority=40, reason="",
        ),
        ClassifiedEmail(
            email=_make_email(eid="cached-2"),
            category="meeting", needs_reply=True, priority=70, reason="",
        ),
    ]
    provider = FakeProvider([])  # would be empty if called
    provider.fetch_called = False
    original_fetch = provider.fetch_inbox

    async def _track_fetch(*args, **kwargs):
        provider.fetch_called = True
        return await original_fetch(*args, **kwargs)

    provider.fetch_inbox = _track_fetch  # type: ignore[method-assign]

    state = {"classified": pre, "user_rules": []}
    result = asyncio.run(fetch(state, provider=provider))

    assert provider.fetch_called is False
    assert [e.id for e in result["inbox"]] == ["cached-1", "cached-2"]


# ─── classify ───────────────────────────────────────────────────────────────


def test_classify_empty_inbox_returns_empty():
    state: dict = {"inbox": []}
    client = FakeOpenAIClient('{"results": []}')
    result = asyncio.run(classify(state, openai_client=client, model="m"))
    assert result == {"classified": []}
    # No LLM call made
    assert client.chat.completions.calls == []


def test_classify_short_circuits_when_classified_preloaded():
    """Mirror of fetch's short-circuit: when state already has ``classified``
    populated (preloaded from a previous run), classify must not re-LLM.

    The patch carries a transient ``_cached: True`` flag so the SSE stream
    can render a "缓存" chip on the classify node — distinguishes "we did
    the work" from "we reused what we had".
    """
    pre = [
        ClassifiedEmail(
            email=_make_email(eid="cached-1"),
            category="internal", needs_reply=False, priority=40, reason="",
        ),
    ]
    state = {"classified": pre, "inbox": []}
    client = FakeOpenAIClient('{"results": []}')
    result = asyncio.run(classify(state, openai_client=client, model="m"))
    # Crucially: no LLM call. The patch contains the cache marker (used by
    # the SSE consumer); ``classified`` stays untouched in state.
    assert result == {"_cached": True}
    assert client.chat.completions.calls == []


def test_classify_parses_results_array():
    inbox = [
        _make_email(eid="m1", subject="Production 500"),
        _make_email(eid="m2", subject="Newsletter"),
    ]
    canned = json.dumps({
        "results": [
            {"id": "m1", "category": "urgent_customer", "needs_reply": True,
             "priority": 95, "reason": "outage"},
            {"id": "m2", "category": "marketing", "needs_reply": False,
             "priority": 5, "reason": "promo"},
        ]
    })
    state: dict = {"inbox": inbox}
    client = FakeOpenAIClient(canned)
    result = asyncio.run(classify(state, openai_client=client, model="@Pages/test"))
    classified = result["classified"]
    assert len(classified) == 2
    assert classified[0].email.id == "m1"
    assert classified[0].category == "urgent_customer"
    assert classified[0].priority == 95
    assert classified[1].category == "marketing"
    # The model was passed through
    assert client.chat.completions.calls[0]["model"] == "@Pages/test"


def test_classify_tolerates_emails_key():
    inbox = [_make_email(eid="m1", subject="x")]
    canned = json.dumps({"emails": [
        {"id": "m1", "category": "internal", "needs_reply": False, "priority": 30, "reason": "fyi"}
    ]})
    result = asyncio.run(classify({"inbox": inbox}, openai_client=FakeOpenAIClient(canned), model="m"))
    assert len(result["classified"]) == 1
    assert result["classified"][0].category == "internal"


def test_classify_tolerates_bare_array():
    inbox = [_make_email(eid="m1")]
    canned = json.dumps([
        {"id": "m1", "category": "spam", "needs_reply": False, "priority": 0, "reason": "junk"}
    ])
    result = asyncio.run(classify({"inbox": inbox}, openai_client=FakeOpenAIClient(canned), model="m"))
    assert len(result["classified"]) == 1


def test_classify_unknown_category_coerced_to_other():
    inbox = [_make_email(eid="m1")]
    canned = json.dumps({"results": [
        {"id": "m1", "category": "weirdo", "needs_reply": False, "priority": 50, "reason": ""}
    ]})
    result = asyncio.run(classify({"inbox": inbox}, openai_client=FakeOpenAIClient(canned), model="m"))
    assert result["classified"][0].category == "other"


def test_classify_clamps_priority():
    inbox = [_make_email(eid="m1"), _make_email(eid="m2")]
    canned = json.dumps({"results": [
        {"id": "m1", "category": "internal", "needs_reply": False, "priority": 200, "reason": ""},
        {"id": "m2", "category": "internal", "needs_reply": False, "priority": -5, "reason": ""},
    ]})
    result = asyncio.run(classify({"inbox": inbox}, openai_client=FakeOpenAIClient(canned), model="m"))
    assert result["classified"][0].priority == 100
    assert result["classified"][1].priority == 0


def test_classify_drops_unknown_id():
    inbox = [_make_email(eid="m1")]
    canned = json.dumps({"results": [
        {"id": "m1", "category": "internal", "needs_reply": False, "priority": 50, "reason": ""},
        {"id": "ghost", "category": "internal", "needs_reply": False, "priority": 50, "reason": ""},
    ]})
    result = asyncio.run(classify({"inbox": inbox}, openai_client=FakeOpenAIClient(canned), model="m"))
    assert len(result["classified"]) == 1
    assert result["classified"][0].email.id == "m1"


def test_classify_invalid_json_returns_error():
    inbox = [_make_email(eid="m1")]
    client = FakeOpenAIClient("not json at all")
    result = asyncio.run(classify({"inbox": inbox}, openai_client=client, model="m"))
    assert "errors" in result
    assert "failed to parse" in result["errors"][0]


def test_classify_llm_error_returns_error_state():
    inbox = [_make_email(eid="m1")]
    client = FakeOpenAIClient(RuntimeError("gateway timeout"))
    result = asyncio.run(classify({"inbox": inbox}, openai_client=client, model="m"))
    assert "errors" in result
    assert "gateway timeout" in result["errors"][0]


def test_classify_injects_triage_rules_skill_into_system_prompt():
    """Verify W2 D4: the classify node augments its system prompt with the
    email-triage-rules SKILL.md so user-specific classification preferences
    surface alongside the LLM's general heuristics."""
    inbox = [_make_email(eid="m1", sender="ops@bigclient.com")]
    canned = json.dumps({"results": [{
        "id": "m1", "category": "urgent_customer", "needs_reply": True,
        "priority": 90, "reason": "VIP customer",
    }]})
    client = FakeOpenAIClient(canned)
    asyncio.run(classify({"inbox": inbox}, openai_client=client, model="m"))

    # The first (only) call's system message should include the skill content
    call = client.chat.completions.calls[0]
    system_content = call["messages"][0]["content"]
    assert system_content.startswith("You are an email triage specialist")
    # Skill content markers
    assert "Skill: email-triage-rules" in system_content
    assert "vipcustomer.com" in system_content or "bigclient.com" in system_content


def test_classify_falls_back_gracefully_if_skill_missing(monkeypatch):
    """If the skill loader returns a 'not installed' sentinel, classify
    should still work — it just uses the bare CLASSIFY_SYSTEM prompt."""
    import _nodes

    def _mock_render(name, **kwargs):
        return f"(skill {name!r} not installed)"

    monkeypatch.setattr("_skill_loader.render_skill_for_prompt", _mock_render)

    inbox = [_make_email(eid="m1")]
    canned = json.dumps({"results": [{
        "id": "m1", "category": "internal", "needs_reply": False,
        "priority": 30, "reason": "fyi",
    }]})
    client = FakeOpenAIClient(canned)
    result = asyncio.run(_nodes.classify({"inbox": inbox}, openai_client=client, model="m"))

    assert len(result["classified"]) == 1
    # System prompt should not contain skill markers
    call = client.chat.completions.calls[0]
    system_content = call["messages"][0]["content"]
    assert "Skill: email-triage-rules" not in system_content


def test_classify_injects_triage_rules_skill_into_system_prompt():
    """Verify W2 D4: the classify node augments its system prompt with the
    email-triage-rules SKILL.md so user-specific classification preferences
    surface alongside the LLM's general heuristics."""
    inbox = [_make_email(eid="m1", sender="ops@bigclient.com")]
    canned = json.dumps({"results": [{
        "id": "m1", "category": "urgent_customer", "needs_reply": True,
        "priority": 90, "reason": "VIP customer",
    }]})
    client = FakeOpenAIClient(canned)
    asyncio.run(classify({"inbox": inbox}, openai_client=client, model="m"))

    # The first (only) call's system message should include the skill content
    call = client.chat.completions.calls[0]
    system_content = call["messages"][0]["content"]
    assert system_content.startswith("You are an email triage specialist")
    # Skill content markers
    assert "Skill: email-triage-rules" in system_content
    assert "vipcustomer.com" in system_content or "bigclient.com" in system_content


def test_classify_falls_back_gracefully_if_skill_missing(monkeypatch):
    """If the skill loader returns a 'not installed' sentinel, classify
    should still work — it just uses the bare CLASSIFY_SYSTEM prompt."""
    import _nodes

    def _mock_render(name, **kwargs):
        return f"(skill {name!r} not installed)"

    monkeypatch.setattr("_skill_loader.render_skill_for_prompt", _mock_render)

    inbox = [_make_email(eid="m1")]
    canned = json.dumps({"results": [{
        "id": "m1", "category": "internal", "needs_reply": False,
        "priority": 30, "reason": "fyi",
    }]})
    client = FakeOpenAIClient(canned)
    result = asyncio.run(_nodes.classify({"inbox": inbox}, openai_client=client, model="m"))

    assert len(result["classified"]) == 1
    # System prompt should not contain skill markers
    call = client.chat.completions.calls[0]
    system_content = call["messages"][0]["content"]
    assert "Skill: email-triage-rules" not in system_content


# ─── prioritize ─────────────────────────────────────────────────────────────


def _ce(eid="m1", category="internal", needs_reply=False, priority=50,
        sender="alice@biz.com", has_ics=False, received_at=None):
    return ClassifiedEmail(
        email=_make_email(eid=eid, sender=sender, has_ics=has_ics, received_at=received_at),
        category=category,
        needs_reply=needs_reply,
        priority=priority,
        reason="",
    )


def test_prioritize_empty_classified():
    result = asyncio.run(prioritize({"classified": []}))
    assert result == {"prioritized": [], "cursor": 0}


def test_prioritize_vip_boost_applied():
    state = {
        "classified": [
            _ce(eid="m1", priority=70, sender="ceo@vipcustomer.com", needs_reply=True),
            _ce(eid="m2", priority=70, sender="someone@other.com", needs_reply=True),
        ],
        "user_rules": [UserRule(kind="vip_domain", value="vipcustomer.com")],
    }
    result = asyncio.run(prioritize(state))
    by_id = {p.email.id: p for p in result["prioritized"]}
    assert by_id["m1"].priority == 90  # +20 boost
    assert by_id["m2"].priority == 70


def test_prioritize_ics_boost_only_when_needs_reply():
    state = {
        "classified": [
            _ce(eid="m1", priority=60, has_ics=True, needs_reply=True),
            _ce(eid="m2", priority=60, has_ics=True, needs_reply=False),
        ],
        "user_rules": [],
    }
    result = asyncio.run(prioritize(state))
    by_id = {p.email.id: p for p in result["prioritized"]}
    # m1 boosted to 70, m2 stays at 60 (which still passes min_priority=30)
    assert by_id["m1"].priority == 70
    assert by_id["m2"].priority == 60


def test_prioritize_urgent_customer_multiplier():
    state = {
        "classified": [_ce(eid="m1", category="urgent_customer", priority=70, needs_reply=True)],
        "user_rules": [],
    }
    result = asyncio.run(prioritize(state))
    assert result["prioritized"][0].priority == 84  # int(70 * 1.2)


def test_prioritize_caps_at_100():
    state = {
        "classified": [
            _ce(eid="m1", category="urgent_customer", priority=95,
                sender="ops@vipcustomer.com", needs_reply=True),
        ],
        "user_rules": [UserRule(kind="vip_domain", value="vipcustomer.com")],
    }
    result = asyncio.run(prioritize(state))
    # 95 + 20 = 115 → capped to 100, then *1.2 = 120 → still 100
    assert result["prioritized"][0].priority == 100


def test_prioritize_clamps_spam_to_zero():
    state = {
        "classified": [_ce(eid="m1", category="spam", priority=80)],
        "user_rules": [],
    }
    result = asyncio.run(prioritize(state))
    # spam clamps + drops below threshold + needs_reply=False → not prioritized
    assert result["prioritized"] == []


def test_prioritize_drops_low_priority_no_reply():
    state = {
        "classified": [
            _ce(eid="low", priority=10, needs_reply=False),
            _ce(eid="mid", priority=30, needs_reply=False),
            _ce(eid="hi",  priority=80, needs_reply=False),
            _ce(eid="re",  priority=10, needs_reply=True),
        ],
        "user_rules": [],
    }
    result = asyncio.run(prioritize(state, min_priority=30))
    ids = [p.email.id for p in result["prioritized"]]
    # Drop "low" (priority<30 AND no reply); keep mid/hi/re (re is needs_reply=True)
    assert "low" not in ids
    assert set(ids) == {"mid", "hi", "re"}


def test_prioritize_sort_order_by_priority_then_age():
    early = datetime(2026, 5, 19, 8, 0, tzinfo=timezone.utc)
    late = datetime(2026, 5, 19, 9, 0, tzinfo=timezone.utc)
    state = {
        "classified": [
            _ce(eid="A", priority=80, needs_reply=True, received_at=late),
            _ce(eid="B", priority=80, needs_reply=True, received_at=early),
            _ce(eid="C", priority=60, needs_reply=True, received_at=early),
        ],
        "user_rules": [],
    }
    result = asyncio.run(prioritize(state))
    ids = [p.email.id for p in result["prioritized"]]
    # B before A (same priority, B older); C last (lower priority)
    assert ids == ["B", "A", "C"]


def test_prioritize_resets_cursor():
    state = {
        "classified": [_ce(eid="m1", priority=80, needs_reply=True)],
        "user_rules": [],
        "cursor": 99,
    }
    result = asyncio.run(prioritize(state))
    assert result["cursor"] == 0


def test_prioritize_single_reply_filters_to_target():
    """``task=single_reply`` + ``target_email_id`` → keep ONLY that email."""
    state = {
        "classified": [
            _ce(eid="m1", priority=80, needs_reply=True),
            _ce(eid="m2", priority=70, needs_reply=True),
            _ce(eid="m3", priority=60, needs_reply=True),
        ],
        "user_rules": [],
        "task": "single_reply",
        "target_email_id": "m2",
    }
    result = asyncio.run(prioritize(state))
    assert [c.email.id for c in result["prioritized"]] == ["m2"]


def test_prioritize_single_reply_unknown_id_returns_empty():
    """Unknown target id → empty list + actionable error message.

    Routing handles the empty list gracefully (after_prioritize routes to
    summarize). The ``errors`` entry is surfaced by the SSE consumer so the
    user sees a "缓存可能过期" hint instead of a silent skip-to-summarize
    that looks like the pipeline did nothing.
    """
    state = {
        "classified": [_ce(eid="m1", priority=80, needs_reply=True)],
        "user_rules": [],
        "task": "single_reply",
        "target_email_id": "nonexistent",
    }
    result = asyncio.run(prioritize(state))
    assert result["prioritized"] == []
    assert result.get("errors")
    # Should mention the target id and point the user to a fix
    err = result["errors"][0]
    assert "nonexistent" in err
    assert "强制刷新" in err


def test_prioritize_other_tasks_ignore_target_email_id():
    """target_email_id is only honored in single_reply mode."""
    state = {
        "classified": [
            _ce(eid="m1", priority=80, needs_reply=True),
            _ce(eid="m2", priority=70, needs_reply=True),
        ],
        "user_rules": [],
        "task": "daily_digest",
        "target_email_id": "m1",  # should be ignored
    }
    result = asyncio.run(prioritize(state))
    # Both kept — daily_digest doesn't filter
    assert {c.email.id for c in result["prioritized"]} == {"m1", "m2"}


def test_prioritize_single_reply_keeps_priority_boosts():
    """Even when filtered to one, the boost+sort logic still ran first so
    e.g. VIP boosts are applied. Verifies we don't bypass the rules."""
    state = {
        "classified": [
            _ce(eid="m1", priority=50, needs_reply=True, sender="ceo@vipcustomer.com"),
        ],
        "user_rules": [UserRule(kind="vip_domain", value="vipcustomer.com")],
        "task": "single_reply",
        "target_email_id": "m1",
    }
    result = asyncio.run(prioritize(state))
    assert len(result["prioritized"]) == 1
    # Original 50 + 20 VIP boost = 70
    assert result["prioritized"][0].priority == 70


def test_prioritize_single_reply_bypasses_needs_reply_filter():
    """User explicitly clicked ↩ 处理 on a low-priority, no-reply email
    (e.g. a Gmail "您启用了两步验证" notification). Single-reply must
    keep it — bypassing the ``needs_reply OR priority>=min`` filter that
    daily_digest uses."""
    state = {
        "classified": [
            # priority=10, needs_reply=False — would be filtered out in
            # daily_digest, but single_reply must keep it.
            _ce(eid="m1", priority=10, needs_reply=False, category="notification"),
        ],
        "user_rules": [],
        "task": "single_reply",
        "target_email_id": "m1",
    }
    result = asyncio.run(prioritize(state))
    assert [c.email.id for c in result["prioritized"]] == ["m1"]


def test_prioritize_single_reply_bypasses_spam_zero_priority():
    """Even spam (priority forced to 0) gets drafted when explicitly chosen.
    The user is the source of truth, not the LLM's category guess."""
    state = {
        "classified": [
            _ce(eid="m1", priority=80, needs_reply=False, category="spam"),
        ],
        "user_rules": [],
        "task": "single_reply",
        "target_email_id": "m1",
    }
    result = asyncio.run(prioritize(state))
    # spam clamps priority to 0, but single_reply still keeps it.
    assert len(result["prioritized"]) == 1
    assert result["prioritized"][0].priority == 0


def test_prioritize_skip_email_ids_filters_in_daily_digest():
    """daily_digest with skip_email_ids should drop those emails before
    the draft loop — used after single_reply clicks."""
    state = {
        "classified": [
            _ce(eid="m1", priority=80, needs_reply=True),
            _ce(eid="m2", priority=70, needs_reply=True),
            _ce(eid="m3", priority=60, needs_reply=True),
        ],
        "user_rules": [],
        "task": "daily_digest",
        "skip_email_ids": ["m1", "m3"],
    }
    result = asyncio.run(prioritize(state))
    assert [c.email.id for c in result["prioritized"]] == ["m2"]


def test_prioritize_skip_email_ids_ignored_for_single_reply():
    """single_reply ALWAYS honors target_email_id, even if it's in the
    skip list — explicit user picks override implicit "already done" state."""
    state = {
        "classified": [
            _ce(eid="m1", priority=80, needs_reply=True),
        ],
        "user_rules": [],
        "task": "single_reply",
        "target_email_id": "m1",
        "skip_email_ids": ["m1"],  # would block in daily_digest but not here
    }
    result = asyncio.run(prioritize(state))
    assert [c.email.id for c in result["prioritized"]] == ["m1"]


def test_prioritize_skip_email_ids_empties_to_summarize():
    """If skip list covers all eligible emails, prioritized is empty and
    after_prioritize routes to summarize (no draft loop)."""
    state = {
        "classified": [
            _ce(eid="m1", priority=80, needs_reply=True),
            _ce(eid="m2", priority=70, needs_reply=True),
        ],
        "user_rules": [],
        "task": "daily_digest",
        "skip_email_ids": ["m1", "m2"],
    }
    result = asyncio.run(prioritize(state))
    assert result["prioritized"] == []
