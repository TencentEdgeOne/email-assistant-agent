"""Pytest configuration — bootstrap import path so ``agents/email/*`` is
importable from inside ``tests/`` without a package install.

This mirrors the runtime convention used by ``run.py`` / other handlers:
they prepend their own directory to ``sys.path`` so the underscore-prefixed
helper modules can be imported with bare names (``from _models import ...``).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent  # → agents/email/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _reset_module_singletons():
    """Reset module-level singletons between tests to keep them isolated.

    Both ``_graph._graph_singleton`` and ``_llm._*_singleton`` are caches
    that survive across requests in production but MUST be reset between
    tests — otherwise a fake graph from one test leaks into the next.
    """
    # Imports are deferred so this runs even if a test only needs _models.
    try:
        from _graph import reset_graph_singleton
        reset_graph_singleton()
    except ImportError:
        pass
    try:
        from _llm import reset_singletons
        reset_singletons()
    except ImportError:
        pass
    yield
