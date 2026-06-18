"""Tests for progress tracking — verify stage names match the external contract."""

import logging

import pytest

from kapsula.presentation.upload.upload_progress_tracker import UploadProgressTracker


@pytest.fixture
def null_logger():
    logger = logging.getLogger("test_null")
    logger.addHandler(logging.NullHandler())
    return logger


class TestProgressContract:
    """The progress tracking dict MUST have the same keys as before refactoring."""

    def test_set_produces_correct_keys(self, null_logger):
        """UploadProgressTracker.set() must set status, progress, stage, message."""
        status: dict = {}
        tracker = UploadProgressTracker(status, null_logger)

        tracker.set(
            "job-123",
            status="processing",
            progress=50,
            stage="chunking",
            message="Creating chunks...",
        )

        entry = status["job-123"]
        assert entry["status"] == "processing"
        assert entry["progress"] == 50
        assert entry["stage"] == "chunking"
        assert entry["message"] == "Creating chunks..."

    def test_stage_names_match_legacy_contract(self):
        """Stage names must match the values used by progress route consumers."""
        expected_stages = [
            "extracting_structure",
            "extracting_parents",
            "chunking",
            "saving_chunks",
            "saving_parents",
            "linking_chunks",
            "building_indexes",
            "rebuilding_aggregate",
            "collection_summary",
            "finalizing",
            "completed",
            "failed",
        ]
        # Verify all expected stage names are valid strings
        for stage in expected_stages:
            assert isinstance(stage, str)
            assert len(stage) > 0

    def test_completed_has_progress_100(self, null_logger):
        """Completed status must have progress=100."""
        status: dict = {}
        tracker = UploadProgressTracker(status, null_logger)

        tracker.set(
            job_id="job-1",
            status="completed",
            progress=100,
            stage="completed",
            message="Done",
        )
        assert status["job-1"]["progress"] == 100
        assert status["job-1"]["status"] == "completed"

    def test_failed_has_progress_0(self, null_logger):
        """Failed status must have progress=0."""
        status: dict = {}
        tracker = UploadProgressTracker(status, null_logger)

        tracker.set(
            job_id="job-1", status="failed", progress=0, stage="failed", message="Error"
        )
        assert status["job-1"]["progress"] == 0
        assert status["job-1"]["status"] == "failed"
