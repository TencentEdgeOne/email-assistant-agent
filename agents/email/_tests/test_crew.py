"""Unit tests for the CrewAI sub-pipeline (Day 4).

Covers:
  - Tool helper functions (filesystem-backed lookups)
  - CrewAI tool wrappers (ToneTool / TemplateTool / ThreadContextTool)
  - Agent builders (filter / writer / polisher)
  - Crew assembly (build_email_draft_crew)
  - Skill directory resolution

Live ``Crew.kickoff(...)`` against AI Gateway is integration-only (W3 D1)
and not exercised here.

Run with::

    pytest agents/email/tests/test_crew.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest

from _tools import (
    HAS_CREWAI,
    TemplateTool,
    ThreadContextTool,
    ToneTool,
    lookup_template,
    lookup_thread_context,
    lookup_tone,
)


pytestmark = pytest.mark.skipif(
    not HAS_CREWAI, reason="crewai not installed in this environment"
)


# ─── Pure helper functions (work without crewai too, but covered here) ──────


def test_lookup_tone_returns_skill_md_body():
    out = lookup_tone("formal")
    assert "Tone preset: formal" in out
    assert "friendly_professional" in out  # SKILL.md body content


def test_lookup_tone_default_param():
    out = lookup_tone()
    assert "friendly_professional" in out  # default


def test_lookup_template_meeting_accept_exists():
    out = lookup_template("meeting-accept")
    assert "Friday" in out
    assert "{sender_first_name}" in out


def test_lookup_template_unknown_lists_available():
    out = lookup_template("does-not-exist")
    assert "no template" in out
    assert "meeting-accept" in out
    assert "customer-apology" in out


def test_lookup_thread_context_returns_no_history_for_mock():
    out = lookup_thread_context("thr_anything")
    assert "no prior history" in out.lower()
    assert "thr_anything" in out


# ─── Tool wrappers ──────────────────────────────────────────────────────────


def test_tone_tool_metadata():
    tool = ToneTool()
    assert tool.name == "lookup_tone_guidance"
    assert "tone" in tool.description.lower()


def test_tone_tool_run_returns_string():
    out = ToneTool()._run(tone="apologetic")
    assert isinstance(out, str)
    assert "apologetic" in out


def test_template_tool_metadata():
    tool = TemplateTool()
    assert tool.name == "lookup_reply_template"
    assert "template" in tool.description.lower()


def test_template_tool_run_returns_template():
    out = TemplateTool()._run(template_name="customer-apology")
    assert "Apologies" in out or "apolog" in out.lower()


def test_thread_context_tool_metadata():
    tool = ThreadContextTool()
    assert tool.name == "fetch_thread_history"


# ─── Agent builders ─────────────────────────────────────────────────────────


def _fake_llm():
    """Return something Agent will accept without actually calling it.

    CrewAI 1.14 accepts a string model name OR an LLM instance. We construct
    an LLM with bogus credentials — we never call it, just verify the
    agents are wired up. ``provider="openai"`` skips LiteLLM dispatch.
    """
    from crewai import LLM
    return LLM(
        model="@Pages/test-model",
        provider="openai",
        api_key="sk-test",
        base_url="https://example.invalid/v1",
        timeout=5,
    )


def test_build_filter_agent_has_correct_role_and_tool():
    from _agents import build_filter_agent
    agent = build_filter_agent(_fake_llm())
    assert agent.role == "Email Triage Analyst"
    tool_names = {t.name for t in agent.tools}
    assert "fetch_thread_history" in tool_names


def test_build_writer_agent_has_template_tool():
    from _agents import build_writer_agent
    agent = build_writer_agent(_fake_llm())
    assert agent.role == "Reply Writer"
    tool_names = {t.name for t in agent.tools}
    assert "lookup_reply_template" in tool_names


def test_build_polisher_agent_has_tone_tool():
    from _agents import build_polisher_agent
    agent = build_polisher_agent(_fake_llm())
    assert agent.role == "Voice Polisher"
    tool_names = {t.name for t in agent.tools}
    assert "lookup_tone_guidance" in tool_names


def test_role_to_ui_stage_covers_all_roles():
    from _agents import (
        ROLE_TO_UI_STAGE,
        build_filter_agent,
        build_polisher_agent,
        build_writer_agent,
    )
    llm = _fake_llm()
    agents = [build_filter_agent(llm), build_writer_agent(llm), build_polisher_agent(llm)]
    for a in agents:
        assert a.role in ROLE_TO_UI_STAGE, f"missing UI stage mapping for {a.role}"


# ─── Task builders ──────────────────────────────────────────────────────────


def _sample_classified():
    """Build a ClassifiedEmail for task-builder tests."""
    from datetime import datetime, timezone
    from _models import ClassifiedEmail, Email
    return ClassifiedEmail(
        email=Email(
            id="m1",
            from_="alice@example.com",
            to=["me@example.com"],
            subject="Production 500",
            body_text="The API is returning 500 errors.",
            received_at=datetime(2026, 5, 21, 10, 0, tzinfo=timezone.utc),
            thread_id="thr_m1",
        ),
        category="urgent_customer",
        needs_reply=True,
        priority=95,
        reason="VIP outage",
    )


def _sample_rules():
    from _models import UserRulesBundle
    return UserRulesBundle(
        vip_domains=["example.com"],
        auto_archive=[],
        default_tone="friendly_professional",
        signature="—— Test",
        language="zh-CN",
    )


def test_build_analyze_task_inlines_email_data():
    from _agents import build_filter_agent
    from _tasks import build_analyze_task
    ce = _sample_classified()
    t = build_analyze_task(
        build_filter_agent(_fake_llm()),
        email_sender=ce.email.sender,
        email_subject=ce.email.subject,
        email_body=ce.email.body_text,
        email_thread_id=ce.email.thread_id or "",
        has_ics=ce.email.has_ics,
        category=ce.category,
        reason=ce.reason,
    )
    assert t.name == "analyze_task"
    # Critical: actual email content should be in the description, NOT placeholders
    assert "alice@example.com" in t.description
    assert "Production 500" in t.description
    assert "urgent_customer" in t.description
    # And no leftover {} placeholders
    assert "{email[" not in t.description
    assert "{category}" not in t.description


def test_build_draft_task_includes_regenerate_feedback():
    """When user submits a regenerate decision with feedback, it must
    surface in the draft task description."""
    from _agents import build_filter_agent, build_writer_agent
    from _tasks import build_analyze_task, build_draft_task
    ce = _sample_classified()
    rules = _sample_rules()
    fa = build_filter_agent(_fake_llm())
    wa = build_writer_agent(_fake_llm())
    a = build_analyze_task(
        fa,
        email_sender=ce.email.sender,
        email_subject=ce.email.subject,
        email_body=ce.email.body_text,
        email_thread_id="",
        has_ics=False,
        category=ce.category,
        reason=ce.reason,
    )
    d = build_draft_task(wa, a, language=rules.language, regenerate_feedback="用英文重写")
    assert "USER FEEDBACK" in d.description
    assert "用英文重写" in d.description


def test_build_draft_task_no_feedback_section_when_none():
    from _agents import build_filter_agent, build_writer_agent
    from _tasks import build_analyze_task, build_draft_task
    ce = _sample_classified()
    fa = build_filter_agent(_fake_llm())
    wa = build_writer_agent(_fake_llm())
    a = build_analyze_task(
        fa,
        email_sender=ce.email.sender,
        email_subject=ce.email.subject,
        email_body=ce.email.body_text,
        email_thread_id="",
        has_ics=False,
        category=ce.category,
        reason=ce.reason,
    )
    d = build_draft_task(wa, a, language="zh-CN", regenerate_feedback=None)
    assert "USER FEEDBACK" not in d.description


def test_build_polish_task_uses_pydantic_output():
    from _agents import (
        build_filter_agent,
        build_polisher_agent,
        build_writer_agent,
    )
    from _models import DraftItem
    from _tasks import build_analyze_task, build_draft_task, build_polish_task

    llm = _fake_llm()
    ce = _sample_classified()
    rules = _sample_rules()
    fa = build_filter_agent(llm)
    wa = build_writer_agent(llm)
    pa = build_polisher_agent(llm)
    a = build_analyze_task(
        fa,
        email_sender=ce.email.sender,
        email_subject=ce.email.subject,
        email_body=ce.email.body_text,
        email_thread_id="",
        has_ics=False,
        category=ce.category,
        reason=ce.reason,
    )
    d = build_draft_task(wa, a, language=rules.language)
    p = build_polish_task(
        pa, d, a,
        email_id=ce.email.id,
        email_sender=ce.email.sender,
        email_subject=ce.email.subject,
        default_tone=rules.default_tone,
        signature=rules.signature,
    )
    assert p.name == "polish_task"
    assert p.output_pydantic is DraftItem
    # Inlined values, no placeholders
    assert "m1" in p.description
    assert "alice@example.com" in p.description
    assert "{email[" not in p.description


def test_task_to_card_id_covers_all_three():
    from _tasks import TASK_TO_CARD_ID
    assert set(TASK_TO_CARD_ID) == {"analyze_task", "draft_task", "polish_task"}


# ─── Crew assembly ──────────────────────────────────────────────────────────


def test_build_email_draft_crew_has_three_agents_and_tasks():
    from _crew import build_email_draft_crew
    crew = build_email_draft_crew(
        _fake_llm(),
        classified=_sample_classified(),
        rules=_sample_rules(),
    )
    assert len(crew.agents) == 3
    assert len(crew.tasks) == 3
    roles = {a.role for a in crew.agents}
    assert roles == {"Email Triage Analyst", "Reply Writer", "Voice Polisher"}


def test_build_email_draft_crew_uses_sequential_process():
    from crewai import Process
    from _crew import build_email_draft_crew
    crew = build_email_draft_crew(
        _fake_llm(),
        classified=_sample_classified(),
        rules=_sample_rules(),
    )
    assert crew.process == Process.sequential


def test_build_email_draft_crew_skills_resolved_to_existing_dirs():
    from _crew import _resolve_skill_dirs
    dirs = _resolve_skill_dirs()
    assert dirs, "expected at least one skill dir to be resolved"
    for d in dirs:
        path = Path(d)
        assert path.is_dir(), f"resolved skill dir does not exist: {d}"
        assert (path / "SKILL.md").is_file(), f"missing SKILL.md in {d}"


def test_build_email_draft_crew_disables_internal_memory():
    """Sibling-template convention: rely on ctx.store, not CrewAI Memory."""
    from _crew import build_email_draft_crew
    crew = build_email_draft_crew(
        _fake_llm(),
        classified=_sample_classified(),
        rules=_sample_rules(),
    )
    assert crew.memory is False
