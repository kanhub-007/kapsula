"""Tests for MaintenanceStateManager (JSON-file-backed deferred state).

Classical school: real manager writing to a temp file (filesystem is the
external boundary). Asserts on persisted JSON state, not call interactions.
"""

import json

import pytest

from kapsula.core.domain.entities.collection import Collection as DomainCollection
from kapsula.infrastructure.repositories.processing.maintenance_state_manager import (
    MaintenanceStateManager,
)


def _collection(
    collection_id: str = "coll-1", name: str = "C", account_id=1
) -> DomainCollection:
    return DomainCollection(
        id=10,
        collection_id=collection_id,
        account_id=account_id,
        name=name,
    )


@pytest.fixture
def manager(tmp_path) -> MaintenanceStateManager:
    return MaintenanceStateManager(path=str(tmp_path / "state.json"))


class TestMaintenanceStateManager:
    def test_mark_stale_creates_state(self, manager, tmp_path):
        manager.mark_collection_stale(
            _collection(), summary=True, collection_index=True
        )
        data = json.loads((tmp_path / "state.json").read_text())
        assert data["coll-1"]["summary_stale"] is True
        assert data["coll-1"]["collection_index_stale"] is True
        assert data["coll-1"]["account_index_stale"] is True

    def test_mark_fresh_clears_flags(self, manager):
        manager.mark_collection_stale(_collection())
        # Clear summary + collection_index only; leave account_index stale.
        manager.mark_collection_fresh(
            _collection(), summary=True, collection_index=True, account_index=False
        )
        state = manager.list_stale()
        # account_index still stale (not cleared), so it remains in the list
        assert len(state) == 1
        assert state[0]["account_index_stale"] is True
        assert state[0]["summary_stale"] is False
        assert state[0]["collection_index_stale"] is False

    def test_mark_fresh_clears_all_when_requested(self, manager):
        manager.mark_collection_stale(_collection())
        manager.mark_collection_fresh(
            _collection(),
            summary=True,
            collection_index=True,
            account_index=True,
        )
        assert manager.list_stale() == []

    def test_increment_uploads_tracks_count(self, manager):
        manager.mark_collection_stale(_collection())
        manager.increment_uploads("coll-1")
        manager.increment_uploads("coll-1")
        state = manager.list_stale()[0]
        assert state["uploads_since_consolidation"] == 2
        assert state["consolidation_stale"] is True

    def test_mark_consolidated_resets_counters(self, manager):
        manager.mark_collection_stale(_collection())
        manager.increment_uploads("coll-1")
        manager.increment_uploads("coll-1")
        manager.mark_consolidated("coll-1")
        state = manager.list_stale()
        # consolidation_stale cleared, but summary/index flags may remain
        coll = [s for s in state if s["collection_id"] == "coll-1"]
        assert coll == [] or coll[0]["consolidation_stale"] is False
        # The consolidation counters are reset on the persisted record:
        # verify by re-loading the raw file.
        # (list_stale filters by stale flags, so check mark_consolidated returns reset.)
        result = manager.mark_consolidated("coll-1")
        assert result["uploads_since_consolidation"] == 0
        assert result["consolidation_stale"] is False

    def test_list_stale_excludes_fresh(self, manager):
        manager.mark_collection_stale(_collection("a"))
        manager.mark_collection_stale(_collection("b"))
        manager.mark_collection_fresh(
            _collection("a"),
            summary=True,
            collection_index=True,
            account_index=True,
        )
        stale_ids = {s["collection_id"] for s in manager.list_stale()}
        assert stale_ids == {"b"}

    def test_state_survives_restart(self, tmp_path):
        path = str(tmp_path / "state.json")
        MaintenanceStateManager(path=path).mark_collection_stale(_collection())
        # A new instance pointing at the same file must see prior state.
        state = MaintenanceStateManager(path=path).list_stale()
        assert len(state) == 1
        assert state[0]["collection_id"] == "coll-1"

    def test_corrupt_json_treated_as_empty(self, tmp_path, caplog):
        path = tmp_path / "state.json"
        path.write_text("{ not valid json")
        manager = MaintenanceStateManager(path=str(path))
        # Must not raise; returns empty state.
        assert manager.list_stale() == []
