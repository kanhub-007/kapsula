"""Tests for UploadIngestionStrategy implementations (S1.1).

Black-box: each strategy implements three ctx-taking methods
(``build_indexes``, ``update_collection_summary``, ``rebuild_aggregates``)
and carries a ``mode`` string — NOT boolean flags. The old
``build_document_indexes`` / ``update_collection_summary`` /
``rebuild_aggregate_indexes`` boolean attributes must be gone.

Fast's methods are no-ops (calling them leaves the context unchanged).
The deeper behavioural tests (does Indexed actually build indexes?) are
Slice 4's scope (S4.1); this scenario only asserts the Strategy shape.
"""

from __future__ import annotations

import pytest

from kapsula.core.application.dto.upload_pipeline_context import (
    UploadPipelineContext,
)
from kapsula.core.application.use_cases.upload.fast_upload_ingestion_strategy import (
    FastUploadIngestionStrategy,
)
from kapsula.core.application.use_cases.upload.full_upload_ingestion_strategy import (
    FullUploadIngestionStrategy,
)
from kapsula.core.application.use_cases.upload.indexed_upload_ingestion_strategy import (
    IndexedUploadIngestionStrategy,
)
from kapsula.core.domain.entities.document import Document

# ── helpers ──────────────────────────────────────────────────────────


_REQUIRED_METHODS = ("build_indexes", "update_collection_summary", "rebuild_aggregates")


def _has_method(obj, name) -> bool:
    return callable(getattr(obj, name, None))


@pytest.fixture
def document() -> Document:
    return Document(id=1, job_id="job-1", filename="doc.md")


@pytest.fixture
def ctx(document):
    """A context with sentinel deps — Fast's no-op methods won't touch them."""
    return UploadPipelineContext(
        db=object(),
        document=document,
        job_id="job-1",
        ingestion_mode="fast",
        start_time=0.0,
        markdown_content="",
        chunker=object(),
        embedder=object(),
        progress=object(),
        maintenance_state=object(),
        card_repo=object(),
        chunk_repo=object(),
    )


# ── structural shape ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "strategy_cls,expected_mode",
    [
        (FastUploadIngestionStrategy, "fast"),
        (IndexedUploadIngestionStrategy, "indexed"),
        (FullUploadIngestionStrategy, "full"),
    ],
)
class TestStrategyShape:
    def test_has_mode_attribute(self, strategy_cls, expected_mode):
        strategy = strategy_cls()
        assert strategy.mode == expected_mode

    def test_has_three_ctx_methods(self, strategy_cls, expected_mode):
        strategy = strategy_cls()
        for method_name in _REQUIRED_METHODS:
            assert _has_method(
                strategy, method_name
            ), f"{strategy_cls.__name__} missing method {method_name}"

    def test_strategy_has_methods_not_boolean_dataclass_fields(
        self, strategy_cls, expected_mode
    ):
        """Strategies are plain classes with ctx-taking methods, not frozen
        dataclasses with boolean fields (closes P1).

        Backward-compat ``@property`` bridges for the old flag names may
        exist temporarily (removed in Slice 2 when tasks.py is rewritten),
        so we assert the strategies are NOT ``@dataclass`` types and that
        the three ctx-taking methods are callable.
        """
        strategy = strategy_cls()
        # Not a dataclass — no __dataclass_fields__.
        assert not hasattr(
            strategy, "__dataclass_fields__"
        ), f"{strategy_cls.__name__} is still a @dataclass; should be a plain class"
        # All three ctx-taking methods exist and are callable.
        for method_name in _REQUIRED_METHODS:
            assert callable(
                getattr(strategy, method_name, None)
            ), f"{strategy_cls.__name__} missing callable method {method_name}"


# ── Fast strategy methods ────────────────────────────────────────────


class _RecordingMaintenanceState:
    """Records mark_stale / increment calls for outcome assertions."""

    def __init__(self, sink: list):
        self._sink = sink

    def mark_collection_stale(self, collection, **kwargs):
        self._sink.append({"method": "mark_collection_stale", "collection": collection})

    def increment_uploads(self, collection_id):
        self._sink.append(
            {"method": "increment_uploads", "collection_id": collection_id}
        )


class TestFastStrategyIsNoOp:
    def test_build_indexes_does_not_touch_context(self, ctx):
        before = dict(ctx.__dict__)
        FastUploadIngestionStrategy().build_indexes(ctx)
        assert ctx.__dict__ == before

    def test_update_collection_summary_does_not_touch_context(self, ctx):
        before = dict(ctx.__dict__)
        FastUploadIngestionStrategy().update_collection_summary(ctx)
        assert ctx.__dict__ == before

    def test_rebuild_aggregates_marks_deferred_maintenance(self, ctx):
        """Fast mode skips aggregate rebuild but marks the collection stale
        so deferred maintenance picks it up (preserves old behaviour).
        Asserts on the outcome (maintenance state was notified), not on calls."""
        from kapsula.core.domain.entities.collection import Collection

        recorded = []
        ctx.maintenance_state = _RecordingMaintenanceState(recorded)
        ctx.document.collection = Collection(collection_id="coll-x", name="X")

        FastUploadIngestionStrategy().rebuild_aggregates(ctx)

        assert any(call["method"] == "mark_collection_stale" for call in recorded)
        assert any(call["method"] == "increment_uploads" for call in recorded)


# ── factory still works ──────────────────────────────────────────────


class TestFactoryReturnsNewShape:
    def test_factory_returns_strategy_with_methods_not_flags(self):
        from kapsula.core.application.use_cases.upload.upload_ingestion_strategy_factory import (
            UploadIngestionStrategyFactory,
        )

        for mode in ("fast", "indexed", "full"):
            strategy = UploadIngestionStrategyFactory.create(mode)
            assert strategy.mode == mode
            for method_name in _REQUIRED_METHODS:
                assert _has_method(strategy, method_name)
