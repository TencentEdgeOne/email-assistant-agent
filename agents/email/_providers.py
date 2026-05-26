"""Email provider abstraction.

The graph nodes only depend on the ``EmailProvider`` Protocol (defined here),
so swapping mock fixtures for a live IMAP mailbox is a one-line change in
``get_provider`` based on the ``EMAIL_PROVIDER`` env var.

Default = ``mock``: reads RFC 5322 ``.eml`` files from ``fixtures/inbox/``
and persists drafts to ``ctx.kv``. Zero external dependencies — `git clone`
and the demo runs.

Set ``EMAIL_PROVIDER=imap`` to use ``imap_tools`` against a real mailbox;
required env vars are ``IMAP_HOST``, ``IMAP_USER``, ``IMAP_APP_PASSWORD``
(see ``.env.example``). The IMAP path lands in Week 3 D3 — Day 2 ships a
stub with the right signatures so callers can swap providers without
touching graph code.

Design notes:
  - All methods are async to match the platform ``ctx.kv`` interface.
  - The mock provider tolerates ``kv=None`` (so unit tests don't need a stub
    for fetch / load_user_rules).
  - ``DraftItem`` ids are namespaced (``draft_mock_``) so it's obvious from
    a kv dump which provider produced them.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any, Optional, Protocol

from _models import DraftItem, Email, UserRulesBundle


# ─── Public Protocol ─────────────────────────────────────────────────────────


class EmailProvider(Protocol):
    """Abstract mailbox interface — the graph only ever calls these methods."""

    async def fetch_inbox(
        self, since: Optional[datetime] = None, limit: int = 50
    ) -> list[Email]: ...

    async def save_draft(self, draft: DraftItem) -> str: ...

    async def archive(self, email_id: str) -> None: ...

    async def mark_read(self, email_id: str) -> None: ...

    async def load_user_rules(self) -> UserRulesBundle: ...


# ─── EML parsing helpers ─────────────────────────────────────────────────────


_FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"


def _parse_address(value: str) -> str:
    """Return ``Name <email>`` if both present, else just the address."""
    name, addr = parseaddr(value or "")
    if not addr:
        return value or ""
    if name:
        return f"{name} <{addr}>"
    return addr


def _split_address_list(value: Optional[str]) -> list[str]:
    """Split a header value like ``a@x.com, "Name" <b@y.com>`` into entries."""
    if not value:
        return []
    return [_parse_address(p) for p in value.split(",") if p.strip()]


def _safe_text(part: EmailMessage) -> str:
    """Decode a non-multipart MIME part as text, falling back gracefully."""
    try:
        payload = part.get_content()
        return payload if isinstance(payload, str) else str(payload)
    except (LookupError, KeyError, ValueError):
        raw = part.get_payload(decode=True)
        if isinstance(raw, (bytes, bytearray)):
            return raw.decode("utf-8", errors="replace")
        return str(raw or "")


def _extract_bodies(msg: EmailMessage) -> tuple[str, Optional[str]]:
    """Return ``(plain_text, html_or_none)`` from a parsed ``EmailMessage``."""
    plain: list[str] = []
    html: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            ctype = part.get_content_type()
            # Skip attachments (filename present)
            if part.get_filename():
                continue
            if ctype == "text/plain":
                plain.append(_safe_text(part))
            elif ctype == "text/html":
                html.append(_safe_text(part))
    else:
        plain.append(_safe_text(msg))
    plain_combined = "\n\n".join(p for p in plain if p)
    html_combined = "\n\n".join(h for h in html if h) or None
    return plain_combined, html_combined


def _detect_attachments(msg: EmailMessage) -> tuple[list[str], bool]:
    """Walk parts, list attachment filenames + flag if any is an ICS."""
    files: list[str] = []
    has_ics = False
    if not msg.is_multipart():
        return files, has_ics
    for part in msg.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        ctype = part.get_content_type()
        if filename:
            files.append(filename)
        if ctype == "text/calendar" or (filename and filename.lower().endswith(".ics")):
            has_ics = True
    return files, has_ics


def _thread_id_for(msg: EmailMessage, message_id: str) -> str:
    """Stable thread id: hash of References (root) > In-Reply-To > Message-ID."""
    refs = (msg.get("References") or "").strip()
    in_reply = (msg.get("In-Reply-To") or "").strip()
    if refs:
        # Use the very first reference (root of the thread)
        root = refs.split()[0].strip("<>")
        return f"thr_{hashlib.sha1(root.encode()).hexdigest()[:12]}"
    if in_reply:
        return f"thr_{hashlib.sha1(in_reply.strip('<>').encode()).hexdigest()[:12]}"
    return f"thr_{hashlib.sha1(message_id.encode()).hexdigest()[:12]}"


def _parse_eml(raw: bytes, fallback_id: str) -> Email:
    """Parse RFC 5322 bytes into an ``Email`` model.

    ``fallback_id`` is used when the EML is missing a Message-ID header
    (some old fixtures or hand-written drafts).
    """
    msg: EmailMessage = BytesParser(policy=policy.default).parsebytes(raw)
    body_text, body_html = _extract_bodies(msg)
    files, has_ics = _detect_attachments(msg)
    message_id = (msg.get("Message-ID") or fallback_id).strip("<>")
    received_str = msg.get("Date")
    try:
        received_at = (
            parsedate_to_datetime(received_str) if received_str else datetime.now(timezone.utc)
        )
    except (TypeError, ValueError):
        received_at = datetime.now(timezone.utc)
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)

    return Email(
        id=message_id,
        from_=_parse_address(msg.get("From") or ""),
        to=_split_address_list(msg.get("To")),
        cc=_split_address_list(msg.get("Cc")),
        subject=msg.get("Subject") or "",
        body_text=body_text.strip(),
        body_html=body_html,
        received_at=received_at,
        thread_id=_thread_id_for(msg, message_id),
        has_ics=has_ics,
        attachments=files,
    )


# ─── KV key helpers ──────────────────────────────────────────────────────────


def _draft_kv_key(email_id: str) -> str:
    return f"drafts:{email_id}"


def _drafts_index_key() -> str:
    return "drafts:_index"


def _archived_key(email_id: str) -> str:
    return f"archived:{email_id}"


def _read_key(email_id: str) -> str:
    return f"read:{email_id}"


# ─── KV adapter (handles both sync and async stubs) ──────────────────────────


async def _maybe_await(value: Any) -> Any:
    """Await value if it's a coroutine; pass through otherwise."""
    if asyncio.iscoroutine(value):
        return await value
    return value


# ─── MockProvider ────────────────────────────────────────────────────────────


class MockProvider:
    """Reads ``fixtures/inbox/*.eml`` and persists drafts to ``ctx.kv``.

    Used by default (``EMAIL_PROVIDER`` unset or ``= mock``). Deterministic —
    you get the same 10 emails every run, which is exactly what you want for
    demos and tests.

    ``archive`` / ``mark_read`` are no-ops on the mailbox itself but they
    record state in ``ctx.kv`` so the apply node and the UI can show what
    *would* have happened against a real mailbox.
    """

    def __init__(
        self,
        fixture_dir: Path | None = None,
        kv: Any | None = None,
        *,
        respect_since: bool = False,
    ) -> None:
        """
        Args:
            fixture_dir: directory of ``.eml`` files. Defaults to the bundled
                ``fixtures/inbox/``.
            kv: per-route KV (used by ``archive`` / ``mark_read`` to record
                "what would have happened"). Optional — tests pass ``None``.
            respect_since: if True, ``fetch_inbox(since=...)`` filters by the
                fixture's Date header; if False (default), all fixtures are
                returned regardless. The default is False because the bundled
                ``.eml`` fixtures have absolute dates baked in (e.g. 2026-05-19),
                so any user running the demo on a later date would otherwise
                see an empty inbox. Real ``IMAPProvider`` instances always
                respect ``since``.
        """
        self.fixture_dir = fixture_dir or (_FIXTURE_ROOT / "inbox")
        self.kv = kv  # may be None during unit tests
        self.respect_since = respect_since

    async def fetch_inbox(
        self, since: Optional[datetime] = None, limit: int = 50
    ) -> list[Email]:
        if not self.fixture_dir.is_dir():
            return []
        emails: list[Email] = []
        for path in sorted(self.fixture_dir.glob("*.eml")):
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            try:
                email = _parse_eml(raw, fallback_id=path.stem)
            except Exception:
                # Bad fixture — skip rather than crashing the whole run
                continue
            # Skip the date filter for mock fixtures by default — see __init__.
            if self.respect_since and since and email.received_at < since:
                continue
            emails.append(email)
            if len(emails) >= limit:
                break
        return emails

    async def save_draft(self, draft: DraftItem) -> str:
        draft_id = f"draft_mock_{uuid.uuid4().hex[:10]}"
        record = {
            "draft_id": draft_id,
            "email_id": draft.email_id,
            "saved_at": _now_ms(),
            "draft": draft.model_dump(),
        }
        if self.kv is not None:
            await self._kv_set(_draft_kv_key(draft.email_id), record)
            index = await self._kv_get_json(_drafts_index_key()) or []
            if isinstance(index, list) and draft.email_id not in index:
                index.append(draft.email_id)
                await self._kv_set(_drafts_index_key(), index)
        return draft_id

    async def archive(self, email_id: str) -> None:
        if self.kv is not None:
            await self._kv_set(_archived_key(email_id), {"at": _now_ms()})

    async def mark_read(self, email_id: str) -> None:
        if self.kv is not None:
            await self._kv_set(_read_key(email_id), {"at": _now_ms()})

    async def load_user_rules(self) -> UserRulesBundle:
        rules_path = _FIXTURE_ROOT / "user_rules.json"
        if rules_path.is_file():
            try:
                data = json.loads(rules_path.read_text(encoding="utf-8"))
                return UserRulesBundle.model_validate(data)
            except (json.JSONDecodeError, ValueError):
                pass
        return UserRulesBundle()

    # ── kv helpers (tolerate test stubs) ──

    async def _kv_set(self, key: str, value: Any) -> None:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        await _maybe_await(self.kv.set(key, text))

    async def _kv_get_json(self, key: str) -> Any:
        try:
            raw = await _maybe_await(self.kv.get(key, type="text"))
        except TypeError:
            # Older stubs without the ``type`` kwarg
            raw = await _maybe_await(self.kv.get(key))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None


# ─── IMAPProvider (Week 3 D3 — full implementation) ─────────────────────────


class IMAPProvider:
    """Real mailbox provider, backed by ``imap_tools``.

    Connection model: open + login + logout per call. EdgeOne agent handlers
    are short-lived; long-lived connections would risk being killed mid-flight
    by the SCF runtime. The cost (~200ms IMAP login per call) is acceptable
    for a triage workflow that runs once per cron tick or per user click.

    Folder semantics:
      - ``fetch_inbox`` reads from ``INBOX``
      - ``save_draft`` APPENDs to a Drafts folder. The folder is discovered
        per RFC 6154 by querying ``LIST`` for the ``\\Drafts`` SPECIAL-USE
        flag — that means a Chinese Gmail account writes to ``[Gmail]/草稿``
        and a Japanese account writes to ``[Gmail]/下書き`` automatically,
        without env hardcoding. Fall-through order:
          1. ``self.drafts_folder`` (if user set ``IMAP_DRAFTS_FOLDER``)
          2. Folder advertising the ``\\Drafts`` SPECIAL-USE flag
          3. ``DEFAULT_DRAFTS_FOLDERS`` (legacy hard-coded names — works on
             servers that don't advertise SPECIAL-USE flags)
      - ``archive`` moves out of ``INBOX`` to ``self.archive_folder``
        (default ``Archive``). For Gmail this just removes the INBOX label.
      - ``mark_read`` sets the ``\\Seen`` flag.

    Email IDs are IMAP UIDs (stable per folder). Operations that take an
    email_id assume the message is currently in INBOX.

    Gmail setup:
      1. Enable two-factor auth at https://myaccount.google.com
      2. Generate App Password at https://myaccount.google.com/apppasswords
      3. Set env: ``EMAIL_PROVIDER=imap``, ``IMAP_HOST=imap.gmail.com``,
         ``IMAP_USER=<your gmail>``, ``IMAP_APP_PASSWORD=<16-char password>``
    """

    # Last-ditch fallback list when the server doesn't advertise SPECIAL-USE
    # flags (very rare on modern IMAP). The discovery path via \Drafts flag
    # is what works for Gmail, Outlook, Fastmail, and Dovecot.
    DEFAULT_DRAFTS_FOLDERS = (
        "[Gmail]/Drafts",
        "[Gmail]/草稿",
        "[Gmail]/下書き",
        "Drafts",
        "INBOX.Drafts",
    )

    def __init__(
        self,
        host: str,
        user: str,
        app_password: str,
        *,
        port: int = 993,
        use_ssl: bool = True,
        drafts_folder: str | None = None,
        archive_folder: str = "Archive",
    ) -> None:
        self.host = host
        self.user = user
        self.app_password = app_password
        self.port = port
        self.use_ssl = use_ssl
        # If the user explicitly set IMAP_DRAFTS_FOLDER, prefer it; else
        # we'll discover via \Drafts SPECIAL-USE flag at write time.
        self.drafts_folder = drafts_folder
        self.archive_folder = archive_folder
        # Cache of the discovered \Drafts folder per provider instance —
        # avoids re-listing folders on every save_draft call. Only set after
        # the first successful discovery (None until then).
        self._discovered_drafts_folder: str | None = None

    # ── Connection helpers ─────────────────────────────────────────────────

    def _login_sync(self):
        """Open and login a MailBox. Sync — wrap in to_thread."""
        try:
            from imap_tools import MailBox, MailBoxUnencrypted
        except ImportError as exc:
            raise RuntimeError(
                "imap-tools not installed. Add it to requirements.txt or "
                "stay on EMAIL_PROVIDER=mock for local dev."
            ) from exc
        cls = MailBox if self.use_ssl else MailBoxUnencrypted
        print(
            f"[IMAPProvider] connecting to {self.host}:{self.port} "
            f"(ssl={self.use_ssl}, user={self.user})",
            flush=True,
        )
        box = cls(self.host, port=self.port).login(self.user, self.app_password)
        print("[IMAPProvider] login OK", flush=True)
        return box

    async def _with_box(self, fn):
        """Run ``fn(box)`` (sync) inside a thread, ensuring login + logout."""
        box = await asyncio.to_thread(self._login_sync)
        try:
            return await asyncio.to_thread(fn, box)
        finally:
            try:
                await asyncio.to_thread(box.logout)
            except Exception:
                # Logout failures are noisy but harmless — the connection
                # will time out server-side either way.
                pass

    # ── EmailProvider interface ────────────────────────────────────────────

    async def fetch_inbox(
        self, since: Optional[datetime] = None, limit: int = 50
    ) -> list[Email]:
        """Read up to ``limit`` recent messages from INBOX, optionally
        filtered to those received after ``since``.

        Fallback: if the date filter returns 0 results (common when the user
        just connected a test mailbox with no recent activity), retry WITHOUT
        the date filter to grab the most recent ``limit`` messages regardless
        of when they arrived. This prevents the confusing "configured IMAP
        but inbox is empty" experience.
        """
        from imap_tools import AND

        # imap_tools' date filter is day-level (IMAP SEARCH SINCE is too).
        criteria = AND(date_gte=since.date()) if since else AND(all=True)

        def _fetch(box) -> list[Email]:
            results: list[Email] = []
            count = 0
            for msg in box.fetch(criteria, mark_seen=False, headers_only=False, reverse=True):
                if count >= limit:
                    break
                try:
                    results.append(_imap_msg_to_email(msg))
                    count += 1
                except Exception as exc:
                    # Log but skip malformed messages
                    print(f"[IMAPProvider] skipping message (parse error): {exc}", flush=True)
                    continue
            return results

        results = await self._with_box(_fetch)
        print(
            f"[IMAPProvider] fetch_inbox: {len(results)} emails"
            f" (since={since.isoformat() if since else 'none'}, limit={limit})",
            flush=True,
        )

        # Fallback: if date filter returned nothing, retry without it.
        # Common scenario: user just configured IMAP on a mailbox that hasn't
        # received mail in the last few days. Without this fallback they'd see
        # "今日无新邮件" and think their config is broken.
        # Cap at 20 to avoid pulling thousands of old emails.
        if not results and since is not None:
            print(
                "[IMAPProvider] date filter returned 0 results — retrying without date filter (max 20)",
                flush=True,
            )
            fallback_criteria = AND(all=True)
            fallback_limit = min(limit, 20)

            def _fetch_all(box) -> list[Email]:
                out: list[Email] = []
                count = 0
                for msg in box.fetch(fallback_criteria, mark_seen=False, headers_only=False, reverse=True):
                    if count >= fallback_limit:
                        break
                    try:
                        out.append(_imap_msg_to_email(msg))
                        count += 1
                    except Exception:
                        continue
                return out

            results = await self._with_box(_fetch_all)
            print(f"[IMAPProvider] fallback fetch: {len(results)} emails", flush=True)

        return results

    async def save_draft(self, draft: DraftItem) -> str:
        """APPEND the draft to a Drafts folder. Returns an opaque draft id.

        Discovery order:
          1. ``self.drafts_folder`` if user set ``IMAP_DRAFTS_FOLDER``
          2. The folder advertising ``\\Drafts`` SPECIAL-USE flag (RFC 6154).
             This is what makes Chinese / Japanese Gmail "just work"
             (``[Gmail]/草稿`` / ``[Gmail]/下書き``) without env hardcoding.
          3. ``DEFAULT_DRAFTS_FOLDERS`` legacy hard-coded names.

        On success, the actual folder used is exposed via ``draft_id`` so
        callers can surface "saved to: <folder>" to the user.
        """
        rfc822 = _draft_to_rfc822_bytes(draft, sender_email=self.user)

        def _append(box) -> str:
            # Build candidate list:  user-set → discovered → defaults
            candidates: list[str] = []
            seen: set[str] = set()

            def _add(name: str | None) -> None:
                if name and name not in seen:
                    seen.add(name)
                    candidates.append(name)

            _add(self.drafts_folder)

            # Cached discovery — only list folders once per provider instance.
            if self._discovered_drafts_folder is None:
                self._discovered_drafts_folder = _discover_special_use_folder(
                    box, "\\Drafts"
                ) or ""  # "" sentinel means "we tried, none found"
            if self._discovered_drafts_folder:
                _add(self._discovered_drafts_folder)

            for name in self.DEFAULT_DRAFTS_FOLDERS:
                _add(name)

            last_exc: Exception | None = None
            for folder in candidates:
                try:
                    # imap_tools.append wants bytes + folder; flag_set to
                    # mark as Draft so most clients render it correctly.
                    box.append(rfc822, folder, flag_set=("\\Draft",))
                    return (
                        f"imap_draft_{folder}_"
                        f"{int(datetime.now(timezone.utc).timestamp() * 1000)}"
                    )
                except Exception as exc:
                    last_exc = exc
                    continue
            raise RuntimeError(
                "Could not APPEND to any candidate Drafts folder "
                f"({candidates!r}). Last error: {last_exc}. "
                "Hint: set IMAP_DRAFTS_FOLDER explicitly in .env, or check "
                "that your account exposes a folder with the \\Drafts "
                "SPECIAL-USE flag (run mail.folder.list() to inspect)."
            )

        return await self._with_box(_append)

    async def archive(self, email_id: str) -> None:
        """Move the message identified by IMAP UID out of INBOX."""

        def _move(box) -> None:
            box.move([email_id], self.archive_folder)

        await self._with_box(_move)

    async def mark_read(self, email_id: str) -> None:
        """Set the ``\\Seen`` flag on the message."""

        def _seen(box) -> None:
            box.flag([email_id], "\\Seen", True)

        await self._with_box(_seen)

    async def load_user_rules(self) -> UserRulesBundle:
        """User rules live in ``ctx.kv`` regardless of mailbox provider; the
        IMAP path doesn't have a natural place to store them. Subclass or
        wrap with a kv-aware decorator if you want persistent rules."""
        return UserRulesBundle()


# ─── IMAP <-> Email model converters ────────────────────────────────────────


def _imap_msg_to_email(msg: Any) -> Email:
    """Convert an ``imap_tools.MailMessage`` to our ``Email`` Pydantic model."""
    # received_at — imap_tools yields a datetime (or None for malformed)
    received = getattr(msg, "date", None)
    if not isinstance(received, datetime):
        received = datetime.now(timezone.utc)
    if received.tzinfo is None:
        received = received.replace(tzinfo=timezone.utc)

    # Attachments: imap_tools exposes .attachments as a list of MailAttachment
    attachment_names: list[str] = []
    has_ics = False
    for att in getattr(msg, "attachments", []) or []:
        name = getattr(att, "filename", "") or ""
        attachment_names.append(name)
        if name.lower().endswith(".ics") or "calendar" in (
            getattr(att, "content_type", "") or ""
        ).lower():
            has_ics = True

    # Thread id: prefer Message-ID header (RFC standard); fall back to UID.
    thread_id: Optional[str] = None
    headers = getattr(msg, "headers", None) or {}
    for key in ("message-id", "Message-ID", "Message-Id"):
        if key in headers:
            value = headers[key]
            if isinstance(value, (list, tuple)) and value:
                thread_id = str(value[0])
            else:
                thread_id = str(value)
            break

    return Email(
        id=str(getattr(msg, "uid", "") or ""),
        from_=getattr(msg, "from_", "") or "",
        to=list(getattr(msg, "to", []) or []),
        cc=list(getattr(msg, "cc", []) or []),
        subject=getattr(msg, "subject", "") or "",
        body_text=getattr(msg, "text", "") or "",
        body_html=getattr(msg, "html", None),
        received_at=received,
        thread_id=thread_id or str(getattr(msg, "uid", "")) or None,
        has_ics=has_ics,
        attachments=attachment_names,
    )


def _draft_to_rfc822_bytes(
    draft: DraftItem, *, sender_email: str | None = None
) -> bytes:
    """Build a minimal RFC 5322 message from our ``DraftItem``.

    Setting ``From:`` matters: Gmail's IMAP server does NOT auto-populate it
    on APPEND, and the Drafts UI uses From: when rendering the row. Without
    it the draft shows up with an empty sender column. ``sender_email``
    should be the authenticated IMAP user when calling from ``IMAPProvider``.
    """
    import email.message
    import email.utils

    msg = email.message.EmailMessage()
    msg["Subject"] = draft.subject or "(no subject)"
    if sender_email:
        msg["From"] = sender_email
    if draft.to:
        msg["To"] = ", ".join(draft.to)
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid()
    msg.set_content(draft.body or "", charset="utf-8")
    return msg.as_bytes()


def _discover_special_use_folder(box: Any, flag: str) -> str | None:
    """Find the folder advertising a SPECIAL-USE flag (RFC 6154).

    ``flag`` is e.g. ``"\\Drafts"``, ``"\\Sent"``, ``"\\Archive"``. Returns
    the folder name (e.g. ``[Gmail]/草稿``) or None if no folder advertises
    it. Tolerates servers that don't expose flags via ``folder.list()`` —
    in that case returns None and the caller falls back to hard-coded names.
    """
    try:
        folders = box.folder.list()
    except Exception:
        return None
    for f in folders:
        flags = getattr(f, "flags", None) or ()
        if flag in flags:
            return getattr(f, "name", None) or None
    return None


# ─── Misc ────────────────────────────────────────────────────────────────────


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


# ─── Factory ─────────────────────────────────────────────────────────────────


def get_provider(env: dict, kv: Any | None = None) -> EmailProvider:
    """Pick a provider based on ``EMAIL_PROVIDER`` env var. Defaults to mock."""
    flavor = (env.get("EMAIL_PROVIDER") or "mock").strip().lower()
    if flavor == "imap":
        host = env.get("IMAP_HOST") or ""
        user = env.get("IMAP_USER") or ""
        password = env.get("IMAP_APP_PASSWORD") or ""
        if not host or not user or not password:
            raise RuntimeError(
                "EMAIL_PROVIDER=imap requires IMAP_HOST, IMAP_USER, IMAP_APP_PASSWORD"
            )
        return IMAPProvider(
            host=host,
            user=user,
            app_password=password,
            port=int(env.get("IMAP_PORT") or 993),
            use_ssl=(str(env.get("IMAP_USE_SSL", "true")).lower() != "false"),
            drafts_folder=(env.get("IMAP_DRAFTS_FOLDER") or None),
            archive_folder=(env.get("IMAP_ARCHIVE_FOLDER") or "Archive"),
        )
    return MockProvider(fixture_dir=_FIXTURE_ROOT / "inbox", kv=kv)
