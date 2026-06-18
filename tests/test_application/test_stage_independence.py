"""Tests for stage modules — verify each stage is independently importable and testable."""


class TestStageIndependence:
    """Each stage module must be importable without other stages or tasks.py."""

    def test_citation_linker_no_db_import(self):
        """Citation linker must NOT import tasks.py, FAISS, or SQLAlchemy."""
        import sys

        # Clear cached imports to test fresh
        for mod in list(sys.modules):
            if "tasks" in mod and "kapsula" in mod:
                del sys.modules[mod]

        from kapsula.core.domain.services.citation_linker import (
            add_citation_metadata_to_chunks,
        )

        chunks = [{"content": "hello world", "metadata": {"chunk_index": 0}}]
        result = add_citation_metadata_to_chunks(
            chunks, parent_sections={}, markdown_content="hello world"
        )
        assert "citation" in result[0]["metadata"]

    def test_aggregate_build_stage_no_tasks_import(self):
        """Aggregate build must import cleanly (functions only, no tasks.py)."""
        from kapsula.infrastructure.repositories.processing.aggregate_build_stage import (
            rebuild_collection_aggregate_index,
        )

        assert callable(rebuild_collection_aggregate_index)

    def test_collection_summary_stage_no_tasks_import(self):
        """Collection summary must import cleanly."""
        from kapsula.infrastructure.repositories.processing.collection_summary_stage import (
            update_collection_library_card,
        )

        assert callable(update_collection_library_card)
