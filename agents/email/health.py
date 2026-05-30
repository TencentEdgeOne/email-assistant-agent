"""POST /email/health — basic health probe.

Also exposes the current EMAIL_PROVIDER so the frontend can show the right
data-source indicator on the onboarding panel (mock vs imap vs gmail).
"""
from __future__ import annotations

import time


async def handler(context):
    env = getattr(context, "env", None) or {}
    provider = (env.get("EMAIL_PROVIDER") or "mock").strip().lower()
    return {
        "status": "ok",
        "ts": int(time.time() * 1000),
        "conversationId": getattr(context, "conversation_id", None),
        "runId": getattr(context, "run_id", None),
        "framework": "langgraph+crewai",
        "agent": "email-assistant",
        "emailProvider": provider,
    }
