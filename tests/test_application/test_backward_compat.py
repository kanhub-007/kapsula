"""Verify backward compatibility — old imports from tasks.py still resolve."""

import pytest


class TestBackwardCompatibility:
    """Imports that existed before the pipeline refactoring must still work."""

    def test_process_document_importable(self):
        """process_document must be importable from tasks.py."""
        from kapsula.presentation.api.tasks import process_document

        assert callable(process_document)

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
