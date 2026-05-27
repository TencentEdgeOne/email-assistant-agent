"""POST /email/history — conversation history (list / get / delete).

The platform's ``ctx.store`` (a ``ConversationMemory`` instance) gives us a
ready-made messages + metadata index — same primitive the openai-agents-test
template uses. We layer thin actions on top:

  - ``action: "list"``   → ``ctx.store.list_conversations(...)`` →
                            [{id, title, createdAt, lastMessageAt, count}, ...]
  - ``action: "get"``    → ``ctx.store.get_messages(id)`` plus
                            ``app.aget_state(...)`` — the messages drive the
                            timeline rebuild, the state rebuilds classified +
                            doneEmailIds in the left column.
  - ``action: "delete"`` → ``ctx.store.delete_conversation(id)`` (idempotent).

Title derivation: we use the FIRST user message's content as the title (à la
ChatGPT). ``run.py`` appends "[task] 仅分类 / 处理待回邮件 / 单独处理"
on session start, so titles look like "仅分类" / "处理待回邮件" out of the
box. Truncated to 60 chars.

Limits: the platform's memory module caps ``get_messages`` and
``list_conversations`` at ``limit=100``. We pick lower numbers (50 for list,
100 for get) so we never trip ``MemoryValidationError`` and so cold-loading
a large conversation isn't slow.
"""
from __future__ import annotations

import asyncio
import sys
import traceback
from pathlib import Path

CURRENT = Path(__file__).resolve().parent
if str(CURRENT) not in sys.path:
    sys.path.insert(0, str(CURRENT))


VALID_ACTIONS = {"list", "get", "delete"}

# Platform memory caps (from .edgeone/agent-python/_platform/memory.py:_MAX_LIMIT).
# Stay strictly under so a future bump of MAX_LIMIT doesn't catch us by surprise.
_LIST_LIMIT = 50
_MESSAGES_LIMIT = 100  # max allowed; conversations rarely exceed this here


def _safe_text(content) -> str:
    """``Message.content`` can be str OR list (multimodal). Reduce to a single
    line of text so the sidebar can display a title without further work."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # multimodal — pick the first text-ish chunk
        for c in content:
            if isinstance(c, dict):
                t = c.get("text") or c.get("content")
                if isinstance(t, str) and t:
                    return t
            elif isinstance(c, str) and c:
                return c
    return ""


def _derive_title(messages: list) -> str:
    """First user message wins — same pattern as ChatGPT/Claude history.
    Falls back to the first non-empty message content if no user role."""
    for m in messages:
        if (m.get("role") or "").lower() == "user":
            t = _safe_text(m.get("content"))
            if t:
                return t[:60]
    for m in messages:
        t = _safe_text(m.get("content"))
        if t:
            return t[:60]
    return "(无消息)"


def _msg_to_dict(m) -> dict:
    """Coerce a ``Message`` (dataclass) → plain dict for the wire.
    ``Message.to_dict()`` is the canonical path; falls back to ``__dict__``
    or ``dict(m)`` in case the platform swaps the shape under us."""
    if hasattr(m, "to_dict"):
        return m.to_dict()
    if hasattr(m, "__dict__"):
        return {k: v for k, v in m.__dict__.items() if not k.startswith("_")}
    try:
        return dict(m)
    except Exception:
        return {"content": str(m), "role": "system"}


async def _handle_list(context):
    store = getattr(context, "store", None)
    if store is None:
        return {"conversations": []}

    result = await store.list_conversations(limit=_LIST_LIMIT, order="desc")

    # Dedupe by conversation_id. The platform's index keys include the
    # ``last_message_at`` timestamp; appending a message writes a new index
    # key and tries to delete the old. In dev mode (local blob store) the
    # delete occasionally races / fails, leaving stale index entries that
    # all resolve to the SAME conversation_id → list_conversations returns
    # the meta multiple times. We surface the most recent one only.
    seen_ids: set[str] = set()
    unique_metas = []
    for meta in getattr(result, "items", []):
        if meta.conversation_id in seen_ids:
            continue
        seen_ids.add(meta.conversation_id)
        unique_metas.append(meta)

    # Fast path vs slow path.
    #
    # Fast path: ``run.py`` writes ``metadata.title`` on the conversation's
    # first message. We can assemble the row entirely from the meta — no
    # extra store I/O. This applies to every conversation created after
    # the metadata-title rollout, which is essentially all of them after
    # the first run of each session.
    #
    # Slow path (legacy): older conversations created before the title
    # was persisted to metadata. We fall back to the original logic of
    # fetching the first few messages and deriving a title from the
    # first user message. Done in parallel via asyncio.gather so a list
    # with many legacy items still loads quickly.
    fast_items: list[dict] = []
    needs_fallback = []
    for meta in unique_metas:
        title = (meta.metadata or {}).get("title")
        if title:
            fast_items.append({
                "id": meta.conversation_id,
                "title": title,
                "createdAt": meta.created_at,
                "lastMessageAt": meta.last_message_at,
                "messageCount": meta.message_count,
            })
        else:
            needs_fallback.append(meta)

    async def _fetch_title(meta) -> dict:
        msg_dicts = []
        try:
            msgs = await store.get_messages(
                conversation_id=meta.conversation_id,
                limit=5,
                order="asc",
            )
            msg_dicts = [_msg_to_dict(m) for m in msgs]
        except Exception:
            pass
        return {
            "id": meta.conversation_id,
            "title": _derive_title(msg_dicts) or meta.conversation_id,
            "createdAt": meta.created_at,
            "lastMessageAt": meta.last_message_at,
            "messageCount": meta.message_count,
        }

    fallback_items: list[dict] = []
    if needs_fallback:
        fallback_items = list(
            await asyncio.gather(*[_fetch_title(m) for m in needs_fallback])
        )

    items = fast_items + fallback_items
    # Re-sort: fast and slow paths are merged out of order — keep the
    # frontend's expected "newest first" by lastMessageAt.
    items.sort(key=lambda x: x.get("lastMessageAt") or 0, reverse=True)

    return {
        "conversations": items,
        "nextCursor": getattr(result, "next_cursor", None),
    }


async def _handle_get(context, body: dict):
    cid = body.get("id") or getattr(context, "conversation_id", None)
    if not cid or not isinstance(cid, str):
        return {"status_code": 400, "body": {"error": "id required"}}

    store = getattr(context, "store", None)
    if store is None:
        return {"id": cid, "messages": [], "state": None}

    # Read messages — best-effort. A brand-new conversation_id (e.g. on first
    # mount before any task ran) will have an empty result; the platform
    # returns [] not an error in that case.
    msg_dicts: list[dict] = []
    try:
        msgs = await store.get_messages(
            conversation_id=cid,
            limit=_MESSAGES_LIMIT,
            order="asc",
        )
        msg_dicts = [_msg_to_dict(m) for m in msgs]
    except Exception as exc:
        # MemoryNotFoundError → conversation has no meta yet. That's fine
        # for a brand-new tab — return empty messages so the frontend can
        # render the onboarding panel without flashing an error.
        if "not found" not in str(exc).lower():
            print(f"[history] get_messages({cid}) error: {exc}", flush=True)
            traceback.print_exc()

    # Best-effort state lookup. The graph-state JSON is heavy (full classified
    # list, drafts, etc.) — exactly what the frontend needs to rebuild the
    # left + center columns when the user clicks a past session. Fails
    # silently for conversations without a graph checkpoint (e.g. the user
    # JUST opened the tab — there's no /email/run history yet).
    #
    # ``next_nodes`` is the LangGraph snapshot's ``next`` tuple — the list of
    # nodes scheduled to run after this checkpoint. When the graph is paused
    # at an ``interrupt()`` call inside the ``review`` node, ``next == ('review',)``
    # — that's the signal the frontend uses to restore the DraftReviewCard
    # after a page refresh. Empty tuple = run finished or never started.
    state_values: dict | None = None
    next_nodes: list[str] = []
    try:
        from _graph import get_graph
        from _llm import DEFAULT_MODEL, get_crewai_llm, get_env, get_openai_client
        from _providers import get_provider
        from _sse_utils import to_jsonable

        env = get_env(getattr(context, "env", None))
        llm = get_crewai_llm(env)
        openai_client = get_openai_client(env)
        provider = get_provider(getattr(context, "env", None) or {}, getattr(context, "kv", None))
        checkpointer = context.store.langgraph_checkpointer

        app = get_graph(
            checkpointer=checkpointer,
            provider=provider,
            llm=llm,
            openai_client=openai_client,
            model=DEFAULT_MODEL,
        )
        snap = await app.aget_state({"configurable": {"thread_id": cid}})
        if snap and snap.values:
            state_values = to_jsonable(dict(snap.values))
        if snap and snap.next:
            # snap.next is a tuple of strings — convert for JSON.
            next_nodes = [str(n) for n in snap.next]
    except Exception as exc:
        # Don't fail the whole call — just return messages without state.
        print(f"[history] aget_state({cid}) skipped: {exc}", flush=True)
        state_values = None
        next_nodes = []

    return {
        "id": cid,
        "messages": msg_dicts,
        "state": state_values,
        "nextNodes": next_nodes,
    }


async def _handle_delete(context, body: dict):
    cid = body.get("id")
    if not cid or not isinstance(cid, str):
        return {"status_code": 400, "body": {"error": "id required"}}

    store = getattr(context, "store", None)
    if store is None:
        return {"deleted": False, "reason": "no store"}

    try:
        await store.delete_conversation(cid)
    except Exception as exc:
        # Treat NotFound as success — caller wants the row gone, and it is.
        if "not found" in str(exc).lower():
            return {"deleted": True}
        print(f"[history] delete_conversation({cid}) error: {exc}", flush=True)
        traceback.print_exc()
        return {"status_code": 500, "body": {"error": f"delete failed: {exc}"}}
    return {"deleted": True}


async def handler(context):
    """Top-level dispatcher.

    Wraps the entire body in try/except so an unexpected backend exception
    becomes a structured error response (with the message visible client-side
    in /email/history's response body) instead of a generic 500. The frontend
    surfaces these via HistorySidebar's error banner.
    """
    try:
        body = (getattr(getattr(context, "request", None), "body", None) or {})
        if not isinstance(body, dict):
            body = {}

        action = str(body.get("action") or "").strip().lower()
        if action not in VALID_ACTIONS:
            return {
                "status_code": 400,
                "body": {
                    "error": f"action must be one of {sorted(VALID_ACTIONS)}",
                    "got": body.get("action"),
                },
            }

        if action == "list":
            return await _handle_list(context)
        if action == "get":
            return await _handle_get(context, body)
        if action == "delete":
            return await _handle_delete(context, body)
        return {"status_code": 400, "body": {"error": f"unknown action: {action}"}}
    except Exception as exc:
        # Print the full traceback to the dev server logs so we can debug
        # in the terminal — and return a JSON body the frontend can show.
        tb = traceback.format_exc()
        print(f"[history] handler error: {exc}\n{tb}", flush=True)
        return {
            "status_code": 500,
            "body": {
                "error": str(exc),
                "type": type(exc).__name__,
                # Keep traceback short for the wire (last 1.5KB) — full
                # version is in the dev-server log.
                "traceback": tb[-1500:],
            },
        }
