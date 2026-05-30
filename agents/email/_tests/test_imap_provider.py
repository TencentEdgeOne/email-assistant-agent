"""Unit tests for the IMAPProvider full implementation (W3 D3).

These tests don't connect to a real IMAP server — they use a fake MailBox
(via monkeypatch) so the connect/login/logout flow runs but every IMAP
operation is captured for assertions. Real Gmail integration is exercised
manually (see README "接真实邮箱" + the e2e_curl.sh script).

Run with::

    pytest agents/email/tests/test_imap_provider.py -v
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from _models import DraftItem, Email
from _providers import (
    IMAPProvider,
    _draft_to_rfc822_bytes,
    _imap_msg_to_email,
)


# ─── Fakes ─────────────────────────────────────────────────────────────────


class FakeMailMessage:
    """Stand-in for imap_tools.MailMessage with all the fields our converter reads."""

    def __init__(
        self,
        *,
        uid: str = "100",
        from_: str = "alice@example.com",
        to: tuple[str, ...] = ("me@example.com",),
        cc: tuple[str, ...] = (),
        subject: str = "Hi",
        text: str = "Hello there",
        html: str | None = None,
        date: datetime | None = None,
        attachments: list | None = None,
        headers: dict | None = None,
    ):
        self.uid = uid
        self.from_ = from_
        self.to = to
        self.cc = cc
        self.subject = subject
        self.text = text
        self.html = html
        self.date = date or datetime(2026, 5, 21, 10, 0, tzinfo=timezone.utc)
        self.attachments = attachments or []
        self.headers = headers or {}


class FakeAttachment:
    def __init__(self, filename: str, content_type: str = "application/octet-stream"):
        self.filename = filename
        self.content_type = content_type


class FakeFolderInfo:
    """Stand-in for imap_tools.FolderInfo with name + flags."""

    def __init__(self, name: str, flags: tuple[str, ...] = ()):
        self.name = name
        self.flags = flags
        self.delim = "/"


class FakeFolder:
    """Stand-in for the ``box.folder`` namespace exposing ``list()`` + ``set()``."""

    def __init__(self, folders: list[FakeFolderInfo] | None = None):
        self._folders = folders or []
        self.current: str | None = None

    def list(self):
        return list(self._folders)

    def set(self, name: str) -> None:
        self.current = name


class FakeMailBox:
    """Captures every IMAP method call. Returns canned data for fetch().

    Mimics the imap_tools.MailBox API surface we use:
      - fetch(criteria, ...) → iterable of messages
      - append(bytes, folder, flag_set=...)
      - move(uids, dest)
      - flag(uids, flag, value)
      - folder.list() / folder.set(name)
      - logout()
    """

    def __init__(
        self,
        messages: list[FakeMailMessage] | None = None,
        folders: list[FakeFolderInfo] | None = None,
    ):
        self.messages = messages or []
        self.appended: list[tuple[bytes, str, tuple[str, ...]]] = []
        self.moved: list[tuple[list[str], str]] = []
        self.flagged: list[tuple[list[str], str, bool]] = []
        self.append_failures: dict[str, Exception] = {}  # folder → exception
        self.logged_out = False
        self.folder = FakeFolder(folders)

    def fetch(self, criteria, *, mark_seen=False, headers_only=False, reverse=False):
        # imap_tools yields lazily; we just iterate the list
        out = list(self.messages)
        if reverse:
            out = list(reversed(out))
        return out

    def append(self, raw: bytes, folder: str, *, flag_set: tuple[str, ...] = ()):
        if folder in self.append_failures:
            raise self.append_failures[folder]
        self.appended.append((raw, folder, tuple(flag_set)))

    def move(self, uids, dest: str):
        self.moved.append((list(uids), dest))

    def flag(self, uids, flag: str, value: bool):
        self.flagged.append((list(uids), flag, value))

    def logout(self):
        self.logged_out = True


def _make_provider(box: FakeMailBox, **overrides) -> IMAPProvider:
    """Build an IMAPProvider whose ``_login_sync`` returns the given fake box."""
    p = IMAPProvider(
        host="imap.example.com",
        user="me@example.com",
        app_password="x" * 16,
        **overrides,
    )
    p._login_sync = lambda: box  # type: ignore[method-assign]
    return p


# ─── _imap_msg_to_email converter ──────────────────────────────────────────


def test_converter_basic_fields():
    msg = FakeMailMessage(uid="42", subject="Re: budget", text="ack")
    out = _imap_msg_to_email(msg)
    assert isinstance(out, Email)
    assert out.id == "42"
    assert out.sender == "alice@example.com"
    assert out.subject == "Re: budget"
    assert out.body_text == "ack"


def test_converter_detects_ics_attachment():
    msg = FakeMailMessage(attachments=[FakeAttachment("invite.ics", "text/calendar")])
    out = _imap_msg_to_email(msg)
    assert out.has_ics is True
    assert "invite.ics" in out.attachments


def test_converter_treats_calendar_content_type_as_ics():
    msg = FakeMailMessage(attachments=[FakeAttachment("event.bin", "text/calendar; method=REQUEST")])
    out = _imap_msg_to_email(msg)
    assert out.has_ics is True


def test_converter_falls_back_when_no_ics():
    msg = FakeMailMessage(attachments=[FakeAttachment("report.pdf", "application/pdf")])
    out = _imap_msg_to_email(msg)
    assert out.has_ics is False
    assert out.attachments == ["report.pdf"]


def test_converter_uses_message_id_header_for_thread():
    msg = FakeMailMessage(headers={"message-id": "<abc-123@example.com>"})
    out = _imap_msg_to_email(msg)
    assert out.thread_id == "<abc-123@example.com>"


def test_converter_falls_back_to_uid_when_no_message_id():
    msg = FakeMailMessage(uid="999", headers={})
    out = _imap_msg_to_email(msg)
    assert out.thread_id == "999"


def test_converter_handles_naive_datetime():
    naive = datetime(2026, 5, 21, 10, 0)  # no tzinfo
    msg = FakeMailMessage(date=naive)
    out = _imap_msg_to_email(msg)
    assert out.received_at.tzinfo is not None  # forced to UTC


def test_converter_handles_missing_date():
    msg = FakeMailMessage()
    msg.date = None
    out = _imap_msg_to_email(msg)
    # Defaults to "now" — we just check it didn't crash
    assert isinstance(out.received_at, datetime)


# ─── _draft_to_rfc822_bytes ────────────────────────────────────────────────


def test_rfc822_includes_subject_and_to():
    d = DraftItem(
        email_id="m1", to=["alice@x.com"], subject="Re: Hi",
        body="hello", tone="formal", confidence=0.9, rationale="",
    )
    raw = _draft_to_rfc822_bytes(d)
    assert b"Subject: Re: Hi" in raw
    assert b"alice@x.com" in raw
    assert b"hello" in raw
    # Without sender_email kwarg, no From: header is set — the IMAP server
    # may auto-populate from the authenticated user.
    assert not raw.startswith(b"From:")
    assert b"\nFrom:" not in raw


def test_rfc822_includes_from_when_sender_email_provided():
    """Gmail's Drafts UI uses the From: header to render the row — without it
    the draft shows blank sender. ``IMAPProvider.save_draft`` always passes
    its authenticated user as ``sender_email``."""
    d = DraftItem(
        email_id="m1", to=["alice@x.com"], subject="Re: Hi",
        body="hello", tone="formal", confidence=0.9, rationale="",
    )
    raw = _draft_to_rfc822_bytes(d, sender_email="me@gmail.com")
    assert b"From: me@gmail.com" in raw


def test_rfc822_handles_unicode_body():
    d = DraftItem(
        email_id="m1", to=["x@y.com"], subject="主题",
        body="你好,这是一封中文邮件 🚀", tone="formal", confidence=0.9, rationale="",
    )
    raw = _draft_to_rfc822_bytes(d)
    # Either mime-encoded or utf-8 raw
    decoded = raw.decode("utf-8", errors="replace")
    assert "你好" in decoded or "=?utf-8?" in decoded.lower()


def test_rfc822_falls_back_for_empty_subject():
    d = DraftItem(
        email_id="m1", to=["x@y.com"], subject="",
        body="hi", tone="formal", confidence=0.9, rationale="",
    )
    raw = _draft_to_rfc822_bytes(d)
    assert b"(no subject)" in raw


# ─── IMAPProvider.fetch_inbox ──────────────────────────────────────────────


def test_fetch_inbox_returns_emails_in_reverse_chronological():
    box = FakeMailBox(messages=[
        FakeMailMessage(uid="1", subject="oldest"),
        FakeMailMessage(uid="2", subject="newest"),
    ])
    provider = _make_provider(box)
    emails = asyncio.run(provider.fetch_inbox())
    # We requested reverse=True so newest first
    assert [e.id for e in emails] == ["2", "1"]
    assert box.logged_out is True


def test_fetch_inbox_respects_limit():
    box = FakeMailBox(messages=[FakeMailMessage(uid=str(i)) for i in range(20)])
    provider = _make_provider(box)
    emails = asyncio.run(provider.fetch_inbox(limit=5))
    assert len(emails) == 5


def test_fetch_inbox_skips_malformed():
    """A converter exception on one message must not break the whole pull."""
    bad = FakeMailMessage(uid="1")
    bad.attachments = "not a list"  # will raise in iteration
    good = FakeMailMessage(uid="2")
    box = FakeMailBox(messages=[bad, good])
    provider = _make_provider(box)
    emails = asyncio.run(provider.fetch_inbox())
    # Bad one skipped, good one kept
    assert any(e.id == "2" for e in emails)


# ─── IMAPProvider.save_draft ───────────────────────────────────────────────


def _draft() -> DraftItem:
    return DraftItem(
        email_id="m1", to=["alice@x.com"], subject="Re: Hi",
        body="ok", tone="formal", confidence=0.9, rationale="",
    )


def test_save_draft_picks_first_working_folder():
    """When discovery finds nothing, fall through DEFAULT_DRAFTS_FOLDERS."""
    box = FakeMailBox()  # no folders advertised
    box.append_failures = {
        "[Gmail]/Drafts": Exception("no such mailbox"),
    }
    provider = _make_provider(box)
    draft_id = asyncio.run(provider.save_draft(_draft()))
    assert draft_id.startswith("imap_draft_")
    # Should have fallen through past [Gmail]/Drafts to one of the next entries
    appended_folders = [folder for _, folder, _ in box.appended]
    assert appended_folders[0] != "[Gmail]/Drafts"


def test_save_draft_discovers_special_use_drafts_folder():
    """Real Gmail (Chinese) advertises ``\\Drafts`` flag on ``[Gmail]/草稿`` —
    the SPECIAL-USE discovery path must pick it without env config."""
    box = FakeMailBox(folders=[
        FakeFolderInfo("INBOX", ("\\HasNoChildren",)),
        FakeFolderInfo("[Gmail]/中文草稿测试", ("\\Drafts", "\\HasNoChildren")),
        FakeFolderInfo("[Gmail]/已发邮件", ("\\Sent",)),
    ])
    # All hard-coded English / common-language names fail — the only way
    # this test can succeed is via SPECIAL-USE discovery.
    box.append_failures = {
        f: Exception(f"NO {f} doesn't exist") for f in IMAPProvider.DEFAULT_DRAFTS_FOLDERS
    }
    provider = _make_provider(box)
    draft_id = asyncio.run(provider.save_draft(_draft()))
    assert "[Gmail]/中文草稿测试" in draft_id
    # The discovered folder is what actually got the APPEND
    assert box.appended[-1][1] == "[Gmail]/中文草稿测试"


def test_save_draft_caches_discovered_folder():
    """Folder discovery (a LIST round-trip) should happen once per provider."""
    list_calls = {"n": 0}
    box = FakeMailBox(folders=[
        FakeFolderInfo("[Gmail]/中文草稿测试", ("\\Drafts",)),
    ])
    original_list = box.folder.list

    def _counted_list():
        list_calls["n"] += 1
        return original_list()

    box.folder.list = _counted_list  # type: ignore[method-assign]

    provider = _make_provider(box)
    asyncio.run(provider.save_draft(_draft()))
    asyncio.run(provider.save_draft(_draft()))
    asyncio.run(provider.save_draft(_draft()))
    assert list_calls["n"] == 1


def test_save_draft_explicit_folder_takes_priority():
    """When user sets IMAP_DRAFTS_FOLDER, that folder is tried first."""
    box = FakeMailBox(folders=[
        FakeFolderInfo("[Gmail]/中文草稿测试", ("\\Drafts",)),
    ])
    provider = _make_provider(box, drafts_folder="MyTeam/Drafts")
    asyncio.run(provider.save_draft(_draft()))
    # First attempt = the explicit user-set folder
    assert box.appended[0][1] == "MyTeam/Drafts"


def test_save_draft_respects_explicit_drafts_folder():
    box = FakeMailBox()
    provider = _make_provider(box, drafts_folder="MyTeam/Drafts")
    asyncio.run(provider.save_draft(_draft()))
    # Explicit folder is tried first
    assert box.appended[0][1] == "MyTeam/Drafts"


def test_save_draft_appends_with_draft_flag():
    box = FakeMailBox()
    provider = _make_provider(box)
    asyncio.run(provider.save_draft(_draft()))
    flag_set = box.appended[0][2]
    assert "\\Draft" in flag_set


def test_save_draft_raises_when_all_folders_fail():
    box = FakeMailBox()
    box.append_failures = {
        f: Exception(f"fail on {f}") for f in IMAPProvider.DEFAULT_DRAFTS_FOLDERS
    }
    provider = _make_provider(box)
    with pytest.raises(RuntimeError, match="Could not APPEND"):
        asyncio.run(provider.save_draft(_draft()))


# ─── IMAPProvider.archive / mark_read ──────────────────────────────────────


def test_archive_moves_to_default_folder():
    box = FakeMailBox()
    provider = _make_provider(box)
    asyncio.run(provider.archive("42"))
    assert box.moved == [(["42"], "Archive")]


def test_archive_respects_custom_folder():
    box = FakeMailBox()
    provider = _make_provider(box, archive_folder="Done/2026")
    asyncio.run(provider.archive("99"))
    assert box.moved == [(["99"], "Done/2026")]


def test_mark_read_sets_seen_flag():
    box = FakeMailBox()
    provider = _make_provider(box)
    asyncio.run(provider.mark_read("17"))
    assert box.flagged == [(["17"], "\\Seen", True)]


# ─── load_user_rules ───────────────────────────────────────────────────────


def test_load_user_rules_returns_empty_bundle():
    """IMAP doesn't read rules from the mailbox — empty bundle is the contract."""
    provider = _make_provider(FakeMailBox())
    rules = asyncio.run(provider.load_user_rules())
    assert rules.vip_domains == []
    assert rules.auto_archive == []


# ─── factory hook ──────────────────────────────────────────────────────────


def test_get_provider_imap_passes_through_drafts_folder_env():
    from _providers import get_provider
    env = {
        "EMAIL_PROVIDER": "imap",
        "IMAP_HOST": "imap.example.com",
        "IMAP_USER": "me@x.com",
        "IMAP_APP_PASSWORD": "y" * 16,
        "IMAP_DRAFTS_FOLDER": "MyDrafts",
        "IMAP_ARCHIVE_FOLDER": "MyArchive",
    }
    p = get_provider(env)
    assert isinstance(p, IMAPProvider)
    assert p.drafts_folder == "MyDrafts"
    assert p.archive_folder == "MyArchive"


def test_get_provider_imap_missing_creds_raises():
    from _providers import get_provider
    with pytest.raises(RuntimeError, match="IMAP_HOST"):
        get_provider({"EMAIL_PROVIDER": "imap"})


# ─── Login + logout lifecycle ──────────────────────────────────────────────


def test_logout_runs_even_when_operation_raises():
    """If an IMAP operation throws, logout must still happen — otherwise we
    leak connections to the mail server."""
    box = FakeMailBox()
    # Sabotage append for every folder so save_draft will raise
    box.append_failures = {
        f: Exception("nope") for f in IMAPProvider.DEFAULT_DRAFTS_FOLDERS
    }
    provider = _make_provider(box)
    with pytest.raises(RuntimeError):
        asyncio.run(provider.save_draft(_draft()))
    assert box.logged_out is True
