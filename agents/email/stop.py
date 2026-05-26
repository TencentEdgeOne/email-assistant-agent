"""POST /email/stop — abort the active run for a given conversation.

Mirrors the platform's stop contract: ``ctx.utils.abort_active_run(conversation_id)``
sets the signal that the SSE generator checks via ``request.signal.is_set()`` on
its next iteration, causing it to bail cleanly.
"""
from __future__ import annotations


async def handler(context):
    body = getattr(getattr(context, "request", None), "body", None) or {}
    if not isinstance(body, dict):
        body = {}

    conversation_id = (
        body.get("conversationId")
        or body.get("conversation_id")
        or getattr(context, "conversation_id", None)
    )
    if not conversation_id:
        return {"status_code": 400, "body": {"error": "Missing conversationId"}}

    utils = getattr(context, "utils", None)
    if utils is None:
        return {"status": "noop", "reason": "ctx.utils unavailable", "conversationId": conversation_id}

    result = utils.abort_active_run(conversation_id)
    # result is AbortActiveRunResult — use .aborted bool, not the object itself
    did_abort = getattr(result, "aborted", False) if result else False
    return {
        "status": "aborting" if did_abort else "idle",
        "conversationId": conversation_id,
        "aborted": did_abort,
    }
