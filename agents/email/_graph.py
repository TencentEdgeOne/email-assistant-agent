"""LangGraph compiled-graph factory.

``build_graph`` wires the eight nodes + three conditional edges defined
elsewhere in this package, injects per-run dependencies (provider, llm,
openai_client) via ``functools.partial``, and compiles with the platform's
built-in checkpointer (``ctx.store.langgraph_checkpointer``).

``get_graph`` is the **caller-facing entry point** — it caches the
compiled graph at module level so all handlers (``run.py`` / ``review.py``)
share one instance. This matches the pattern used in the
sibling reference templates (``langgraph-quiz-python``,
``crewai-planner-python``) and is critical for HITL: a fresh compiled
graph per request would reset LangGraph's internal channel versions and
break ``Command(resume=...)`` continuation across requests.

Pipeline:

         ┌─────────┐
         │  fetch  │
         └────┬────┘
              ▼
        ┌──────────┐
        │ classify │
        └────┬─────┘
             ▼
       ┌────────────┐  no emails  ┌───────────┐
       │ prioritize ├────────────►│ summarize │── END
       └────┬───────┘             └───────────┘
            │ has emails               ▲
            ▼                          │ done
      ┌────────────┐                   │
      │   draft    │◄──┐               │
      └────┬───────┘   │ regenerate    │
           ▼           │               │
      ┌────────────┐   │               │
      │   review   │   │               │
      └────┬───────┘   │               │
           │ approve/edit/reject/skip  │
           ▼           │               │
      ┌────────────┐   │ next email    │
      │   apply    ├───┴───────────────┘
      └────────────┘
"""
from __future__ import annotations

from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph

import _nodes
import _routing
from _state import EmailAssistantState


# ─── Module-level singleton ─────────────────────────────────────────────────

_graph_singleton: Any = None


def reset_graph_singleton() -> None:
    """Clear the cached compiled graph. Tests use this between cases."""
    global _graph_singleton
    _graph_singleton = None


def get_graph(
    *,
    checkpointer: Any,
    provider: Any,
    llm: Any,
    openai_client: Any,
    model: str,
) -> Any:
    """Return the (cached) compiled LangGraph application.

    First call compiles + caches; subsequent calls return the same instance.

    All callers must agree on the dependencies. In production these come from
    module-level singletons in ``_llm.py`` / ``_providers.py`` so the
    fingerprint stays stable. If you need to swap deps mid-process (e.g.
    tests), call ``reset_graph_singleton()`` first.
    """
    global _graph_singleton
    if _graph_singleton is None:
        _graph_singleton = build_graph(
            checkpointer=checkpointer,
            provider=provider,
            llm=llm,
            openai_client=openai_client,
            model=model,
        )
    return _graph_singleton


def build_graph(
    *,
    checkpointer: Any,
    provider: Any,
    llm: Any,
    openai_client: Any,
    model: str,
) -> Any:
    """Compile and return the email-assistant LangGraph application.

    Args:
        checkpointer: ``ctx.store.langgraph_checkpointer`` (from the platform).
        provider: ``EmailProvider`` instance (mock or imap).
        llm: CrewAI ``LLM`` for the draft sub-pipeline.
        openai_client: ``openai.AsyncOpenAI`` for classify / summarize nodes.
        model: model id passed to chat.completions (e.g. ``@Makers/...``).

    Returns:
        A compiled LangGraph application ready for ``.astream(...)``.
    """
    g = StateGraph(EmailAssistantState)

    g.add_node("fetch", partial(_nodes.fetch, provider=provider))
    g.add_node("classify", partial(_nodes.classify, openai_client=openai_client, model=model))
    g.add_node("prioritize", _nodes.prioritize)
    g.add_node("draft", partial(_nodes.draft_with_crew, llm=llm))
    g.add_node("review", _nodes.review)
    g.add_node("apply", partial(_nodes.apply, provider=provider))
    g.add_node("summarize", partial(_nodes.summarize, openai_client=openai_client, model=model))

    g.add_edge(START, "fetch")
    g.add_edge("fetch", "classify")
    g.add_edge("classify", "prioritize")
    g.add_conditional_edges(
        "prioritize",
        _routing.after_prioritize,
        {"draft": "draft", "summarize": "summarize"},
    )
    g.add_edge("draft", "review")
    g.add_conditional_edges(
        "review",
        _routing.after_review,
        {"apply": "apply", "draft": "draft"},
    )
    g.add_conditional_edges(
        "apply",
        _routing.next_or_done,
        {"draft": "draft", "summarize": "summarize"},
    )
    g.add_edge("summarize", END)

    return g.compile(checkpointer=checkpointer)
