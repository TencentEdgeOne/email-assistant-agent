"""Tests for ``_skill_loader`` — SKILL.md parsing + render helpers.

Run with::

    pytest agents/email/tests/test_skill_loader.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest

from _skill_loader import (
    list_skills,
    load_skill,
    parse_skill,
    render_skill_for_prompt,
)


SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


# ─── parse_skill ────────────────────────────────────────────────────────────


def test_parse_skill_extracts_frontmatter_fields():
    fm, body = parse_skill(SKILLS_DIR / "email-tone" / "SKILL.md")
    assert fm["name"] == "email-tone"
    assert "tone preset" in fm["description"]
    assert fm["license"] == "Apache-2.0"
    # metadata is a sub-dict
    assert isinstance(fm.get("metadata"), dict)
    assert fm["metadata"]["version"] == "1.0"
    # Body has the actual skill content
    assert "# Email Tone" in body
    assert "friendly_professional" in body


def test_parse_skill_template_has_correct_frontmatter():
    fm, body = parse_skill(SKILLS_DIR / "email-templates" / "SKILL.md")
    assert fm["name"] == "email-templates"
    assert "templates" in fm["description"].lower()
    assert "# Email Templates" in body


def test_parse_skill_missing_file():
    fm, body = parse_skill(SKILLS_DIR / "nonexistent" / "SKILL.md")
    assert fm.get("missing") is True
    assert body == ""


def test_parse_skill_no_frontmatter(tmp_path: Path):
    md = tmp_path / "SKILL.md"
    md.write_text("# Bare\n\nContent only, no frontmatter.\n")
    fm, body = parse_skill(md)
    assert fm == {}
    assert "Bare" in body


def test_parse_skill_with_quoted_values(tmp_path: Path):
    md = tmp_path / "SKILL.md"
    md.write_text("---\nname: quoted\ndescription: \"hello: world\"\n---\nbody")
    fm, _ = parse_skill(md)
    assert fm["name"] == "quoted"
    assert fm["description"] == "hello: world"


def test_parse_skill_list_value(tmp_path: Path):
    md = tmp_path / "SKILL.md"
    md.write_text('---\nname: x\nallowed-tools: ["a", "b", "c"]\n---\n')
    fm, _ = parse_skill(md)
    assert fm["allowed-tools"] == ["a", "b", "c"]


# ─── load_skill ─────────────────────────────────────────────────────────────


def test_load_skill_by_name():
    fm, body = load_skill("email-tone")
    assert fm["name"] == "email-tone"
    assert "Email Tone" in body


def test_load_skill_missing_returns_sentinel():
    fm, body = load_skill("does-not-exist")
    assert fm.get("missing") is True
    assert body == ""


def test_load_skill_with_custom_base(tmp_path: Path):
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: test only\n---\n# Body\n"
    )
    fm, body = load_skill("my-skill", base=tmp_path)
    assert fm["name"] == "my-skill"
    assert "Body" in body


# ─── render_skill_for_prompt ────────────────────────────────────────────────


def test_render_skill_includes_name_description_and_body():
    out = render_skill_for_prompt("email-tone")
    assert "## Skill: email-tone" in out
    assert "tone preset" in out
    assert "friendly_professional" in out


def test_render_skill_truncates_long_body():
    out = render_skill_for_prompt("email-tone", max_chars=400)
    # Total render bounded by max_chars
    assert len(out) <= 400
    assert "truncated" in out


def test_render_missing_skill_returns_sentinel():
    out = render_skill_for_prompt("ghost")
    assert "not installed" in out
    assert "ghost" in out


# ─── list_skills ────────────────────────────────────────────────────────────


def test_list_skills_discovers_both_skills():
    skills = list_skills()
    names = {s["name"] for s in skills}
    assert "email-tone" in names
    assert "email-templates" in names
    # Each entry has a resolved directory path
    for s in skills:
        assert "_dir" in s
        assert Path(s["_dir"]).is_dir()


def test_list_skills_with_empty_dir(tmp_path: Path):
    out = list_skills(base=tmp_path)
    assert out == []


def test_list_skills_skips_dirs_without_skill_md(tmp_path: Path):
    (tmp_path / "no-skill").mkdir()
    (tmp_path / "yes-skill").mkdir()
    (tmp_path / "yes-skill" / "SKILL.md").write_text(
        "---\nname: yes-skill\ndescription: x\n---\n"
    )
    out = list_skills(base=tmp_path)
    names = {s["name"] for s in out}
    assert names == {"yes-skill"}
