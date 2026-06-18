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

    def test_no_boolean_flag_attributes(self, strategy_cls, expected_mode):
        """The old boolean flags must be gone (closes P1).

        Two old flag names (``build_document_indexes``,
        ``rebuild_aggregate_indexes``) don't collide with any method name
        and must be absent entirely. The third (``update_collection_summary``)
        is intentionally reused as the new method name — verify it's now
        callable, not a boolean.
        """
        strategy = strategy_cls()
        # Non-colliding old flag names — must be gone entirely.
        assert not hasattr(strategy, "build_document_indexes")
        assert not hasattr(strategy, "rebuild_aggregate_indexes")
        # Colliding name — must now be a method, not a boolean.
        assert callable(getattr(strategy, "update_collection_summary", None))


# ── Fast strategy methods are no-ops ─────────────────────────────────


class TestFastStrategyIsNoOp:
    def test_build_indexes_does_not_touch_context(self, ctx):
        before = dict(ctx.__dict__)
        FastUploadIngestionStrategy().build_indexes(ctx)
        assert ctx.__dict__ == before

    def test_update_collection_summary_does_not_touch_context(self, ctx):
        before = dict(ctx.__dict__)
        FastUploadIngestionStrategy().update_collection_summary(ctx)
        assert ctx.__dict__ == before

    def test_rebuild_aggregates_does_not_touch_context(self, ctx):
        before = dict(ctx.__dict__)
        FastUploadIngestionStrategy().rebuild_aggregates(ctx)
        assert ctx.__dict__ == before


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
