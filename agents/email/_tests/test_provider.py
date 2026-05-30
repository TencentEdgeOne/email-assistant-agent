"""Unit tests for ``_providers.MockProvider`` + factory.

Run with::

    cd agents/email-assistant
    pytest agents/email/tests/test_provider.py -v

Tests use ``asyncio.run`` directly to avoid a hard dependency on
``pytest-asyncio``. The platform ``ctx.kv`` is stubbed by ``FakeKV``.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from _models import DraftItem, UserRulesBundle
from _providers import IMAPProvider, MockProvider, get_provider


# ─── In-memory KV stub ──────────────────────────────────────────────────────


class FakeKV:
    """Mimics the platform ``ctx.kv`` async interface with an in-memory dict."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str, *, type: str = "text") -> str | None:  # noqa: A002
        return self.store.get(key)

    async def set(self, key: str, value: str) -> None:
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


# ─── fetch_inbox ────────────────────────────────────────────────────────────


def test_fetch_inbox_returns_all_ten_fixtures():
    inbox = asyncio.run(MockProvider().fetch_inbox())
    assert len(inbox) == 10
    for email in inbox:
        assert email.id
        assert email.subject
        assert email.body_text
        assert email.received_at is not None


def test_fetch_inbox_respects_limit():
    inbox = asyncio.run(MockProvider().fetch_inbox(limit=3))
    assert len(inbox) == 3


def test_fetch_inbox_filters_by_since():
    from datetime import datetime, timezone

    # MockProvider ignores ``since`` by default (so the demo always shows all
    # 10 fixtures regardless of today's date). Opt in via respect_since=True
    # to exercise the actual filter logic — which IMAPProvider always uses.
    future = datetime(2026, 6, 1, tzinfo=timezone.utc)
    inbox = asyncio.run(MockProvider(respect_since=True).fetch_inbox(since=future))
    assert inbox == []


def test_fetch_inbox_returns_all_fixtures_by_default():
    """The default MockProvider must return all bundled fixtures regardless
    of how stale their Date headers are — otherwise the demo doesn't work."""
    from datetime import datetime, timezone

    way_in_the_future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    inbox = asyncio.run(MockProvider().fetch_inbox(since=way_in_the_future))
    # Even with an absurd ``since``, all 10 fixtures still come back
    assert len(inbox) == 10


def test_meeting_invite_has_ics_flag():
    inbox = asyncio.run(MockProvider().fetch_inbox())
    meeting = next((e for e in inbox if "Roadshow" in e.subject), None)
    assert meeting is not None, "02-meeting-invite.eml fixture not found"
    assert meeting.has_ics is True
    assert any(name.lower().endswith(".ics") for name in meeting.attachments)
    # The other 9 must NOT have an ICS
    for other in inbox:
        if other is meeting:
            continue
        assert other.has_ics is False, f"{other.subject} should not flag has_ics"


def test_threading_uses_references_when_present():
    inbox = asyncio.run(MockProvider().fetch_inbox())
    # 06-followup.eml has References + In-Reply-To headers
    followup = next((e for e in inbox if "二次跟进" in e.subject), None)
    assert followup is not None
    assert followup.thread_id is not None
    assert followup.thread_id.startswith("thr_")


def test_chinese_subject_and_body_decoded():
    inbox = asyncio.run(MockProvider().fetch_inbox())
    leave = next((e for e in inbox if "请假" in e.subject), None)
    assert leave is not None
    assert "请假" in leave.body_text
    assert "Lily" in leave.sender or "lily" in leave.sender


# ─── save_draft / archive / mark_read ───────────────────────────────────────


def test_save_draft_persists_to_kv():
    kv = FakeKV()
    provider = MockProvider(kv=kv)
    draft = DraftItem(
        email_id="msg-1",
        to=["a@x.com"],
        subject="Re: Hello",
        body="Thanks!",
        tone="friendly_professional",
        confidence=0.9,
        rationale="standard reply",
    )
    draft_id = asyncio.run(provider.save_draft(draft))
    assert draft_id.startswith("draft_mock_")

    # Stored under drafts:{email_id}
    raw = kv.store.get("drafts:msg-1")
    assert raw is not None
    decoded = json.loads(raw)
    assert decoded["draft"]["body"] == "Thanks!"
    assert decoded["email_id"] == "msg-1"

    # Index updated
    index_raw = kv.store.get("drafts:_index")
    assert index_raw is not None
    assert "msg-1" in json.loads(index_raw)


def test_save_draft_idempotent_on_index():
    """Two saves for the same email_id should leave a single index entry."""
    kv = FakeKV()
    provider = MockProvider(kv=kv)
    draft = DraftItem(
        email_id="msg-2",
        to=["a@x.com"],
        subject="Re: Hi",
        body="v1",
        tone="formal",
        confidence=0.5,
        rationale="",
    )
    asyncio.run(provider.save_draft(draft))
    draft.body = "v2"
    asyncio.run(provider.save_draft(draft))
    index = json.loads(kv.store["drafts:_index"])
    assert index.count("msg-2") == 1


def test_save_draft_works_without_kv():
    """Calling save_draft with kv=None should not raise."""
    provider = MockProvider(kv=None)
    draft = DraftItem(
        email_id="msg-3", to=["a@x.com"], subject="x", body="y",
        tone="concise", confidence=0.5, rationale="",
    )
    draft_id = asyncio.run(provider.save_draft(draft))
    assert draft_id.startswith("draft_mock_")


def test_archive_and_mark_read_record_state():
    kv = FakeKV()
    provider = MockProvider(kv=kv)
    asyncio.run(provider.archive("msg-99"))
    asyncio.run(provider.mark_read("msg-99"))
    assert "archived:msg-99" in kv.store
    assert "read:msg-99" in kv.store


# ─── load_user_rules ─────────────────────────────────────────────────────────


def test_load_user_rules_from_fixture():
    rules = asyncio.run(MockProvider().load_user_rules())
    assert isinstance(rules, UserRulesBundle)
    assert "vipcustomer.com" in rules.vip_domains
    assert "news@tool.io" in rules.auto_archive
    assert rules.signature  # non-empty
    assert rules.language == "zh-CN"


# ─── Factory ─────────────────────────────────────────────────────────────────


def test_get_provider_default_is_mock():
    p = get_provider({}, kv=FakeKV())
    assert isinstance(p, MockProvider)


def test_get_provider_explicit_mock_is_mock():
    p = get_provider({"EMAIL_PROVIDER": "mock"}, kv=FakeKV())
    assert isinstance(p, MockProvider)


def test_get_provider_imap_requires_credentials():
    with pytest.raises(RuntimeError, match="IMAP_HOST"):
        get_provider({"EMAIL_PROVIDER": "imap"})


def test_get_provider_imap_constructs_with_credentials():
    p = get_provider({
        "EMAIL_PROVIDER": "imap",
        "IMAP_HOST": "imap.gmail.com",
        "IMAP_USER": "me@x.com",
        "IMAP_APP_PASSWORD": "pw",
    })
    assert isinstance(p, IMAPProvider)
    assert p.host == "imap.gmail.com"
    assert p.user == "me@x.com"
    assert p.port == 993
    assert p.use_ssl is True


def test_imap_use_ssl_can_be_disabled():
    p = get_provider({
        "EMAIL_PROVIDER": "imap",
        "IMAP_HOST": "imap.x.com",
        "IMAP_USER": "u",
        "IMAP_APP_PASSWORD": "pw",
        "IMAP_USE_SSL": "false",
        "IMAP_PORT": "143",
    })
    assert isinstance(p, IMAPProvider)
    assert p.use_ssl is False
    assert p.port == 143


# Note: full IMAP behavior (login flow, save_draft folder discovery, etc.)
# is exercised by ``test_imap_provider.py`` against a fake MailBox. Don't
# duplicate those cases here.
