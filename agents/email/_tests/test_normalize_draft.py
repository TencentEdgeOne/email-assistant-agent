"""Unit tests for ``_nodes._normalize_draft`` — post-LLM safety net.

When the polisher LLM returns malformed drafts (empty subject, just "Re:",
blank body, etc.), the user shouldn't see broken cards in the HITL UI.
``_normalize_draft`` patches these from the source email.

Run with::

    pytest agents/email/tests/test_normalize_draft.py -v
"""
from __future__ import annotations

from datetime import datetime, timezone

from _models import ClassifiedEmail, DraftItem, Email
from _nodes import _normalize_draft, _sanitize_summary_md, _strip_email_markdown


def _ce(subject: str = "Production 500", sender: str = "ops@bigcustomer.com") -> ClassifiedEmail:
    return ClassifiedEmail(
        email=Email(
            id="m1",
            from_=sender,
            to=["me@x.com"],
            subject=subject,
            body_text="hello",
            received_at=datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc),
            thread_id="thr_m1",
        ),
        category="urgent_customer",
        needs_reply=True,
        priority=95,
        reason="VIP outage",
    )


def _draft(**overrides) -> DraftItem:
    base = dict(
        email_id="m1",
        to=["ops@bigcustomer.com"],
        subject="Re: Production 500",
        body="Working on it.",
        tone="urgent",
        confidence=0.85,
        rationale="",
    )
    base.update(overrides)
    return DraftItem(**base)


# ─── subject patching ───────────────────────────────────────────────────────


def test_empty_subject_falls_back_to_re_plus_original():
    out = _normalize_draft(_draft(subject=""), _ce(subject="Production 500"))
    assert out.subject == "Re: Production 500"


def test_just_re_falls_back():
    out = _normalize_draft(_draft(subject="Re:"), _ce(subject="Production 500"))
    assert out.subject == "Re: Production 500"


def test_just_re_with_space_falls_back():
    out = _normalize_draft(_draft(subject="Re: "), _ce(subject="Production 500"))
    assert out.subject == "Re: Production 500"


def test_real_subject_left_alone():
    out = _normalize_draft(
        _draft(subject="Re: Production 500 — Working on it"),
        _ce(subject="Production 500"),
    )
    assert out.subject == "Re: Production 500 — Working on it"


def test_subject_when_original_also_empty():
    out = _normalize_draft(_draft(subject=""), _ce(subject=""))
    assert out.subject == "Re: (无主题)"


# ─── body patching ──────────────────────────────────────────────────────────


def test_empty_body_gets_placeholder():
    out = _normalize_draft(_draft(body=""), _ce())
    assert "草稿生成失败" in out.body
    # Other fields preserved
    assert out.email_id == "m1"
    assert out.subject == "Re: Production 500"


def test_whitespace_only_body_gets_placeholder():
    out = _normalize_draft(_draft(body="   \n  "), _ce())
    assert "草稿生成失败" in out.body


# ─── email_id / to patching ─────────────────────────────────────────────────


def test_missing_email_id_filled_in():
    out = _normalize_draft(_draft(email_id=""), _ce())
    assert out.email_id == "m1"


def test_empty_to_falls_back_to_sender():
    out = _normalize_draft(
        _draft(to=[]),
        _ce(sender="ceo@vipclient.com"),
    )
    assert out.to == ["ceo@vipclient.com"]


# ─── no-op when everything is fine ──────────────────────────────────────────


def test_perfect_draft_passes_through_unchanged():
    d = _draft()
    out = _normalize_draft(d, _ce())
    # Same content (model_copy with no patch returns the same instance)
    assert out is d


def test_multiple_problems_all_fixed_at_once():
    out = _normalize_draft(
        _draft(subject="Re:", body="", to=[], email_id=""),
        _ce(subject="Q3 报告", sender="boss@company.com"),
    )
    assert out.subject == "Re: Q3 报告"
    assert "草稿生成失败" in out.body
    assert out.to == ["boss@company.com"]
    assert out.email_id == "m1"


# ─── markdown-in-body stripping (defensive) ─────────────────────────────────
#
# The polish_task prompt forbids markdown, but LLMs occasionally ignore it
# (especially when adapting markdown reply templates). _strip_email_markdown
# is the enforcement pass — these tests pin its behaviour so a future
# refactor doesn't regress the user-visible "no markdown in my email" promise.


def test_bold_stripped_from_body():
    out = _normalize_draft(
        _draft(body="Thanks for the **detailed proposal**. Looks good."),
        _ce(),
    )
    assert "**" not in out.body
    assert "detailed proposal" in out.body


def test_table_dropped_from_body():
    out = _normalize_draft(
        _draft(
            body=(
                "Pricing tiers:\n\n"
                "| Tier | Price |\n"
                "|------|-------|\n"
                "| Pro  | $99   |\n\n"
                "Let me know."
            ),
        ),
        _ce(),
    )
    # Table rows + separator gone; surrounding prose preserved.
    assert "|" not in out.body
    assert "Pricing tiers" in out.body
    assert "Let me know" in out.body


def test_heading_marker_stripped_from_body():
    out = _normalize_draft(
        _draft(body="## Summary\n\nWe agreed on Q3.\n\n## Next steps\n\nCall Tuesday."),
        _ce(),
    )
    assert "##" not in out.body
    assert "Summary" in out.body
    assert "Next steps" in out.body


def test_bullet_markers_stripped_from_body():
    out = _normalize_draft(
        _draft(
            body=(
                "Key points:\n\n"
                "- First item\n"
                "- Second item\n"
                "- Third item"
            ),
        ),
        _ce(),
    )
    assert "- " not in out.body
    assert "First item" in out.body
    assert "Third item" in out.body


def test_code_fence_unwrapped_in_body():
    out = _normalize_draft(
        _draft(body="Here's the snippet:\n\n```\nsudo apt update\n```\n\nRun that."),
        _ce(),
    )
    assert "```" not in out.body
    assert "sudo apt update" in out.body


def test_link_syntax_flattened():
    out = _normalize_draft(
        _draft(body="See [the docs](https://example.com) for context."),
        _ce(),
    )
    assert "[" not in out.body
    assert "the docs" in out.body
    assert "https://example.com" in out.body


def test_clean_body_passes_through_untouched():
    """Already-plain body is a no-op — important for ``out is d`` semantics
    in the ``test_perfect_draft_passes_through_unchanged`` test above."""
    plain = "Hi Sarah,\n\nThanks for the proposal. Q3 timeline looks tight but doable.\n\nBest,\nJesper"
    assert _strip_email_markdown(plain) == plain


# ─── summary markdown sanitization (frontend can't render tables) ───────────
#
# MarkdownBody in ConversationStream.tsx supports h2/h3, bullets, **bold**,
# inline `code`, and links. Anything else renders as raw text. We strip
# unsupported syntax server-side so the user doesn't see broken `| col |`.


def test_summary_table_dropped():
    out = _sanitize_summary_md(
        "## 概览\n\n| 主题 | 决策 |\n|------|------|\n| Re: A | approve |\n\n## 下一步"
    )
    assert "|" not in out
    assert "## 概览" in out
    assert "## 下一步" in out


def test_summary_numbered_list_converted_to_bullet():
    out = _sanitize_summary_md(
        "## 下一步建议\n\n1. 跟进客户\n2. 安排会议\n3. 复核报告"
    )
    # Frontend MarkdownBody only renders `-`/`*` bullets, not `1. ` numbered.
    assert "- 跟进客户" in out
    assert "- 安排会议" in out
    assert "1." not in out


def test_summary_code_fences_unwrapped():
    out = _sanitize_summary_md("## 命令\n\n```bash\nrun.sh\n```\n\n执行该脚本。")
    assert "```" not in out
    assert "run.sh" in out


def test_summary_headings_and_bullets_preserved():
    """Don't damage syntax the frontend supports — h2, h3, bullet lists,
    bold/italic, inline code, links must all survive."""
    src = (
        "## 概览\n\n"
        "本次处理 **5 封邮件**。\n\n"
        "## 需要关注的\n\n"
        "- [95] 生产 500 — `ops@bigclient.com` — 出货 SLA\n"
        "- [90] SSO 请求 — `ceo@vipcustomer.com`\n\n"
        "### 详情\n\n"
        "查看 [仪表盘](https://dash.example.com)。"
    )
    out = _sanitize_summary_md(src)
    assert "## 概览" in out
    assert "## 需要关注的" in out
    assert "### 详情" in out
    assert "**5 封邮件**" in out
    assert "`ops@bigclient.com`" in out
    assert "[仪表盘](https://dash.example.com)" in out
    assert "- [95]" in out
