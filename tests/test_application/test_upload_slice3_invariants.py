"""Tests for Slice 3 invariants — shared persistence + strategy-method maintenance.

S3.1: Flat and subdocument chunking share one persistence path (no
duplication between the two strategy files).
S3.2: the maintenance step calls strategy methods unconditionally (no
``if strategy.flag:`` branches).

These are structural/behavioural pins so the invariants can't regress.
"""

from __future__ import annotations

import inspect

from kapsula.core.application.use_cases.upload.flat_chunking_strategy import (
    FlatChunkingStrategy,
)
from kapsula.core.application.use_cases.upload.subdocument_chunking_strategy import (
    SubDocumentChunkingStrategy,
)
from kapsula.core.application.use_cases.upload.upload_pipeline import UploadPipeline


class TestS31SharedPersistence:
    """S3.1: persistence is not duplicated across the two chunking strategies."""

    def test_strategies_contain_no_db_persistence_calls(self):
        """Neither chunking strategy may call db.add / db.commit / db.flush
        directly — all persistence goes through upload_persistence helpers."""
        for strategy_cls in (FlatChunkingStrategy, SubDocumentChunkingStrategy):
            source = inspect.getsource(strategy_cls)
            # extract_and_chunk must be pure (no DB writes).
            forbidden = ["db.add", "db.commit", "db.flush", "db.query"]
            leaked = [token for token in forbidden if token in source]
            assert not leaked, (
                f"{strategy_cls.__name__} performs direct DB ops: {leaked}. "
                "Persistence must live in upload_persistence.py."
            )

    def test_both_strategies_delegate_to_shared_persistence_module(self):
        """The pipeline's _chunk_and_persist step is the single persistence
        caller for both shapes (no per-strategy persistence duplication)."""
        source = inspect.getsource(UploadPipeline._chunk_and_persist)
        # Both branches route through upload_persistence helpers.
        assert "persist_flat_chunks" in source or "upload_persistence" in source
        assert "persist_subdocuments" in source or "upload_persistence" in source


class TestS32MaintenanceViaStrategyMethods:
    """S3.2: maintenance step calls strategy methods, no flag branches."""

    def test_run_maintenance_calls_both_strategy_methods(self):
        source = inspect.getsource(UploadPipeline._run_maintenance)
        assert "update_collection_summary" in source
        assert "rebuild_aggregates" in source

    def test_no_flag_branches_in_maintenance_step(self):
        """The maintenance step must not branch on boolean flags."""
        source = inspect.getsource(UploadPipeline._run_maintenance)
        forbidden_flags = ["build_document_indexes", "rebuild_aggregate_indexes"]
        leaked = [flag for flag in forbidden_flags if flag in source]
        assert not leaked, (
            f"_run_maintenance branches on flags: {leaked}. It must call "
            "strategy methods unconditionally."
        )

    def test_no_flag_branches_remain_in_upload_module(self):
        """No file in the upload use-case package branches on the old flags."""
        import os

        import kapsula.core.application.use_cases.upload as pkg

        pkg_dir = os.path.dirname(pkg.__file__)
        for filename in os.listdir(pkg_dir):
            if not filename.endswith(".py") or filename == "__init__.py":
                continue
            path = os.path.join(pkg_dir, filename)
            with open(path) as handle:
                source = handle.read()
            # An ``if x.build_document_indexes:`` branch (not a @property def).
            for flag in ("build_document_indexes", "rebuild_aggregate_indexes"):
                assert (
                    f"if {flag}" not in source and f".{flag}:" not in source
                ), f"{filename} branches on flag {flag}"
