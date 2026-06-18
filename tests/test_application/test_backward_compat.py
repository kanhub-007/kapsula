"""Verify backward compatibility — old imports from tasks.py still resolve."""


class TestBackwardCompatibility:
    """Imports that existed before the pipeline refactoring must still work."""

    def test_process_document_removed_flat_fallback_now_internal(self):
        """process_document is gone (spec S2.3): the flat fallback is now an
        internal strategy swap inside SubDocumentChunkingStrategy. Only the
        subdocument entry point remains."""
        import pytest

        with pytest.raises(ImportError):
            from kapsula.presentation.api.tasks import process_document  # noqa: F401

    def test_process_document_with_subdocuments_importable(self):
        """process_document_with_subdocuments must be importable from tasks.py."""
        from kapsula.presentation.api.tasks import process_document_with_subdocuments

        assert callable(process_document_with_subdocuments)

    def test_get_processing_status_importable(self):
        """get_processing_status must be importable from tasks.py (used by routes)."""
        from kapsula.presentation.api.tasks import get_processing_status

        assert callable(get_processing_status)
        # Called without a job returns None
        assert get_processing_status("nonexistent-job-id") is None
