"""Tests for ``scheduled.py`` cron entry handler.

Validates env + provider + KV plumbing. The full pipeline integration
(against an LLM) is W3 D1; here we exercise everything around the
``ainvoke`` call by injecting fakes via monkeypatch.

Run with::

    pytest agents/email/tests/test_scheduled.py -v
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest

import scheduled as scheduled_module


# ─── Fake context infrastructure ────────────────────────────────────────────


class _Req:
    def __init__(self, body):
        self.body = body
        self.signal = None


class _StubStore:
    def __init__(self):
        from langgraph.checkpoint.memory import InMemorySaver
        self.langgraph_checkpointer = InMemorySaver()


class _Kv:
    """In-memory async KV stub."""
    def __init__(self):
        self.store: dict[str, str] = {}

    async def set(self, key, value):
        self.store[key] = value

    async def get(self, key, **_kwargs):
        return self.store.get(key)


_KV_DEFAULT = object()  # sentinel: distinguish "use default _Kv" from explicit None


class _Ctx:
    def __init__(self, body, env=None, conversation_id="cron", kv=_KV_DEFAULT):
        self.request = _Req(body)
        self.env = env or {}
        self.conversation_id = conversation_id
        self.run_id = "test-run-12345"
        self.kv = _Kv() if kv is _KV_DEFAULT else kv
        self.store = _StubStore()


VALID_ENV = {
    "AI_GATEWAY_API_KEY": "sk-test",
    "AI_GATEWAY_BASE_URL": "https://example.invalid/v1",
}


# ─── Validation / error paths ──────────────────────────────────────────────


def test_missing_env_returns_500():
    ctx = _Ctx({"_schedule": True}, env={})
    out = asyncio.run(scheduled_module.handler(ctx))
    assert out["status_code"] == 500
    assert "AI_GATEWAY" in out["body"]["error"]


def test_partial_env_returns_500():
    ctx = _Ctx(
        {"_schedule": True},
        env={"AI_GATEWAY_API_KEY": "sk"},  # missing AI_GATEWAY_BASE_URL
    )
    out = asyncio.run(scheduled_module.handler(ctx))
    assert out["status_code"] == 500


# ─── Pipeline plumbing (with mocked build_graph) ───────────────────────────


class _FakeApp:
    """Stand-in for the compiled LangGraph app — captures ainvoke calls."""

    def __init__(self, final_state):
        self.final_state = final_state
        self.invocations: list[dict] = []

    async def ainvoke(self, state, config):
        self.invocations.append({"state": state, "config": config})
        return self.final_state


def _patch_build(monkeypatch, fake_app):
    """Replace the heavy deps with no-op factories returning fake_app."""
    monkeypatch.setattr(scheduled_module, "get_graph",
                        lambda **kwargs: fake_app)
    monkeypatch.setattr(scheduled_module, "get_crewai_llm",
                        lambda env: object())
    monkeypatch.setattr(scheduled_module, "get_openai_client",
                        lambda env: object())


def test_cron_run_persists_digest_to_kv(monkeypatch):
    fake_app = _FakeApp({
        "summary": "## 概览\n- 5 封邮件",
        "drafts": [object(), object()],
        "final_actions": [object()],
        "errors": [],
    })
    _patch_build(monkeypatch, fake_app)

    ctx = _Ctx({"_schedule": True, "task": "daily_digest"}, env=VALID_ENV)
    out = asyncio.run(scheduled_module.handler(ctx))

    assert out["status"] == "ok"
    assert out["stored"] is True
    assert out["trigger"] == "schedule"
    assert out["task"] == "daily_digest"
    assert out["drafts_count"] == 2
    assert out["actions_count"] == 1

    today = date.today().isoformat()
    raw = ctx.kv.store[f"digest:{today}"]
    digest = json.loads(raw)
    assert digest["summary"] == "## 概览\n- 5 封邮件"
    assert digest["trigger"] == "schedule"


def test_manual_run_records_manual_trigger(monkeypatch):
    fake_app = _FakeApp({"summary": "ok", "drafts": [], "final_actions": [], "errors": []})
    _patch_build(monkeypatch, fake_app)

    ctx = _Ctx({}, env=VALID_ENV)  # no _schedule flag
    out = asyncio.run(scheduled_module.handler(ctx))
    assert out["trigger"] == "manual"


def test_auto_approve_is_set_in_initial_state(monkeypatch):
    fake_app = _FakeApp({"summary": "x", "drafts": [], "final_actions": [], "errors": []})
    _patch_build(monkeypatch, fake_app)

    ctx = _Ctx({"_schedule": True}, env=VALID_ENV)
    asyncio.run(scheduled_module.handler(ctx))

    state_passed = fake_app.invocations[0]["state"]
    assert state_passed["auto_approve"] is True
    assert state_passed["task"] == "daily_digest"


def test_each_invocation_uses_fresh_thread_id(monkeypatch):
    """Two consecutive cron runs in the same day get DIFFERENT thread_ids
    (so LangGraph doesn't short-circuit on the cached END state)."""
    fake_app = _FakeApp({"summary": "x", "drafts": [], "final_actions": [], "errors": []})
    _patch_build(monkeypatch, fake_app)

    ctx1 = _Ctx({"_schedule": True}, env=VALID_ENV)
    ctx2 = _Ctx({"_schedule": True}, env=VALID_ENV)
    # Override run_id so the thread_id varies
    ctx1.run_id = "run-aaa"
    ctx2.run_id = "run-bbb"

    asyncio.run(scheduled_module.handler(ctx1))
    asyncio.run(scheduled_module.handler(ctx2))

    cfg1 = fake_app.invocations[0]["config"]
    cfg2 = fake_app.invocations[1]["config"]
    assert cfg1["configurable"]["thread_id"] != cfg2["configurable"]["thread_id"]


def test_digest_idempotent_overwrite_in_kv(monkeypatch):
    """Two same-day runs leave a SINGLE digest:YYYY-MM-DD key (overwrite)."""
    kv = _Kv()
    fake_app1 = _FakeApp({"summary": "first", "drafts": [], "final_actions": [], "errors": []})
    _patch_build(monkeypatch, fake_app1)
    ctx1 = _Ctx({"_schedule": True}, env=VALID_ENV, kv=kv)
    asyncio.run(scheduled_module.handler(ctx1))

    fake_app2 = _FakeApp({"summary": "second", "drafts": [object()], "final_actions": [], "errors": []})
    monkeypatch.setattr(scheduled_module, "get_graph",
                        lambda **kwargs: fake_app2)
    ctx2 = _Ctx({"_schedule": True}, env=VALID_ENV, kv=kv)
    asyncio.run(scheduled_module.handler(ctx2))

    today = date.today().isoformat()
    # Only one key with the digest prefix
    digest_keys = [k for k in kv.store if k.startswith("digest:")]
    assert len(digest_keys) == 1
    assert digest_keys[0] == f"digest:{today}"

    # And the second run's content wins
    digest = json.loads(kv.store[digest_keys[0]])
    assert digest["summary"] == "second"
    assert digest["drafts_count"] == 1


def test_pipeline_failure_returns_500(monkeypatch):
    class _Failing:
        async def ainvoke(self, state, config):
            raise RuntimeError("ainvoke exploded")

    monkeypatch.setattr(scheduled_module, "get_graph", lambda **kw: _Failing())
    monkeypatch.setattr(scheduled_module, "get_crewai_llm", lambda env: object())
    monkeypatch.setattr(scheduled_module, "get_openai_client", lambda env: object())

    ctx = _Ctx({"_schedule": True}, env=VALID_ENV)
    out = asyncio.run(scheduled_module.handler(ctx))
    assert out["status_code"] == 500
    assert "ainvoke exploded" in out["body"]["error"]


def test_kv_failure_does_not_fail_response(monkeypatch):
    """If kv.set raises, the handler should still return ok with stored=False."""

    class _BadKv:
        async def set(self, *args, **kwargs):
            raise RuntimeError("kv quota exceeded")

    fake_app = _FakeApp({"summary": "x", "drafts": [], "final_actions": [], "errors": []})
    _patch_build(monkeypatch, fake_app)

    ctx = _Ctx({"_schedule": True}, env=VALID_ENV, kv=_BadKv())
    out = asyncio.run(scheduled_module.handler(ctx))
    assert out["status"] == "ok"
    assert out["stored"] is False


def test_kv_none_does_not_crash(monkeypatch):
    fake_app = _FakeApp({"summary": "x", "drafts": [], "final_actions": [], "errors": []})
    _patch_build(monkeypatch, fake_app)

    ctx = _Ctx({"_schedule": True}, env=VALID_ENV, kv=None)
    out = asyncio.run(scheduled_module.handler(ctx))
    assert out["status"] == "ok"
    assert out["stored"] is False
