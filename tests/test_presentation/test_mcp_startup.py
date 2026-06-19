"""Smoke test: the MCP composition root imports and builds without runtime errors.

Regression guard for a class of bug introduced during the M3 type-annotation
cleanup: a symbol imported only under ``TYPE_CHECKING`` was used as a
runtime-evaluated annotation (``db: Session``) on an ``ABC`` method body.
Without ``from __future__ import annotations`` the annotation is evaluated
at class-definition time, so the module raised ``NameError`` at import —
but only when imported by the actual server entry point, not under the
developer's ``python -c`` (different interpreter/caches).

This test imports the real composition path the way ``run_mcp.py`` does, so
the same crash would fail CI instead of surfacing only at server start.
"""

from kapsula.startup.mcp import create_server


def test_mcp_composition_root_builds():
    """``create_server()`` must import every tool module and return a server."""
    server = create_server()
    assert server is not None


def test_index_manager_module_imports_cleanly():
    """The interface that previously crashed must import without NameError."""
    # Importing the module executes the class body, which is where the
    # TYPE_CHECKING-only ``Session`` annotation was evaluated at runtime.
    import kapsula.core.domain.interfaces.index_manager  # noqa: F401

    from kapsula.core.domain.interfaces.index_manager import IndexManager

    assert IndexManager is not None


def test_collection_maintenance_runner_imports_cleanly():
    """The runner with a TYPE_CHECKING ChatClient annotation must import."""
    import kapsula.presentation.upload.collection_maintenance_runner  # noqa: F401
