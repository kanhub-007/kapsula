"""Deferred maintenance state management."""

import json
import os
import threading
from datetime import UTC, datetime
from typing import Any

from kapsula.infrastructure.data import DATA_DIR, Collection
from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)
_STATE_LOCK = threading.RLock()


class MaintenanceStateManager:
    """Marks and clears deferred collection/account maintenance state.

    State is persisted as JSON under DATA_DIR to avoid schema changes while still
    surviving process restarts.
    """

    def __init__(self, path: str | None = None):
        self._path = path or os.path.join(DATA_DIR, "maintenance_state.json")
        self._cache: dict[str, dict[str, Any]] | None = None

    def mark_collection_stale(
        self,
        collection: Collection,
        *,
        summary: bool = True,
        collection_index: bool = True,
        account_index: bool = True,
    ) -> dict[str, Any]:
        """Mark collection/account derived artifacts as stale."""
        with _STATE_LOCK:
            states = self._load_states()
            key = collection.collection_id
            state = states.get(key, self._new_state(collection))
            self._deduplicate_states(states, collection)
            # Repair null db_ids from legacy increment_uploads entries
            if state.get("collection_db_id") is None:
                state["collection_db_id"] = collection.id
            if state.get("account_db_id") is None and collection.account_id:
                state["account_db_id"] = collection.account_id
            state["summary_stale"] = state["summary_stale"] or summary
            state["collection_index_stale"] = (
                state["collection_index_stale"] or collection_index
            )
            state["account_index_stale"] = state["account_index_stale"] or bool(
                collection.account_id and account_index
            )
            state["updated_at"] = datetime.now(UTC).isoformat()
            states[key] = state
            self._save_states(states)
            return state

    def mark_collection_fresh(
        self,
        collection: Collection,
        *,
        summary: bool = True,
        collection_index: bool = True,
        account_index: bool = True,
        consolidation: bool = False,
    ) -> dict[str, Any]:
        """Clear selected deferred maintenance flags for a collection.

        Consolidation is tracked separately from index/summary maintenance —
        pass ``consolidation=True`` explicitly when you also want to reset
        consolidation state (typically after a successful consolidation run).
        Prefer :meth:`mark_consolidated` for that workflow.
        """
        with _STATE_LOCK:
            states = self._load_states()
            key = collection.collection_id
            self._deduplicate_states(states, collection)
            state = states.get(key, self._new_state(collection))
            # Repair null db_ids from legacy increment_uploads entries
            if state.get("collection_db_id") is None:
                state["collection_db_id"] = collection.id
            if state.get("account_db_id") is None and collection.account_id:
                state["account_db_id"] = collection.account_id
            if summary:
                state["summary_stale"] = False
            if collection_index:
                state["collection_index_stale"] = False
            if account_index:
                state["account_index_stale"] = False
            if consolidation:
                state["consolidation_stale"] = False
                state["uploads_since_consolidation"] = 0
                state["last_consolidation_at"] = datetime.now(UTC).isoformat()
            state["updated_at"] = datetime.now(UTC).isoformat()
            states[key] = state
            self._save_states(states)
            return state

    def list_stale(self) -> list[dict[str, Any]]:
        """Return all states with pending maintenance (including consolidation)."""
        with _STATE_LOCK:
            states = list(self._load_states().values())
        stale = [
            state
            for state in states
            if state.get("summary_stale")
            or state.get("collection_index_stale")
            or state.get("account_index_stale")
            or state.get("consolidation_stale")
        ]
        return sorted(stale, key=lambda item: item.get("updated_at", ""), reverse=True)

    # ── consolidation tracking (Phase 2) ──────────────────────
    def increment_uploads(self, collection_id: str) -> dict[str, Any]:
        """Increment the uploads-since-consolidation counter.

        Called after every upload_document or delete_document on a collection.
        Self-sufficient: if no state exists yet for the collection, creates one
        with consolidation marked stale (closes O3 — no temporal coupling with
        ``mark_collection_stale``).
        """
        with _STATE_LOCK:
            states = self._load_states()
            for _key, state in states.items():
                if state.get("collection_id") == collection_id:
                    state["uploads_since_consolidation"] = (
                        state.get("uploads_since_consolidation", 0) + 1
                    )
                    state["consolidation_stale"] = True
                    state["updated_at"] = datetime.now(UTC).isoformat()
                    self._save_states(states)
                    return state
            # No existing state — create one with consolidation marked stale
            state = {
                "collection_id": collection_id,
                "collection_db_id": None,
                "collection_name": "?",
                "account_db_id": None,
                "summary_stale": False,
                "collection_index_stale": False,
                "account_index_stale": False,
                "consolidation_stale": True,
                "uploads_since_consolidation": 1,
                "last_consolidation_at": None,
                "updated_at": datetime.now(UTC).isoformat(),
            }
            states[collection_id] = state
            self._save_states(states)
            return state

    def mark_consolidated(self, collection_id: str) -> dict[str, Any]:
        """Reset consolidation tracking after a successful consolidation run."""
        with _STATE_LOCK:
            states = self._load_states()
            for _key, state in states.items():
                if state.get("collection_id") == collection_id:
                    state["consolidation_stale"] = False
                    state["uploads_since_consolidation"] = 0
                    state["last_consolidation_at"] = datetime.now(UTC).isoformat()
                    state["updated_at"] = datetime.now(UTC).isoformat()
                    self._save_states(states)
                    return state
            return {}

    # ── internal helpers ──────────────────────────────────────

    @staticmethod
    def _new_state(collection: Collection) -> dict[str, Any]:
        return {
            "collection_db_id": collection.id,
            "collection_id": collection.collection_id,
            "collection_name": collection.name,
            "account_db_id": collection.account_id,
            "summary_stale": False,
            "collection_index_stale": False,
            "account_index_stale": False,
            "consolidation_stale": False,
            "uploads_since_consolidation": 0,
            "last_consolidation_at": None,
            "updated_at": datetime.now(UTC).isoformat(),
        }

    @staticmethod
    def _deduplicate_states(
        states: dict[str, dict[str, Any]], collection: Collection
    ) -> None:
        """Remove stale duplicate entries keyed by DB integer ID.

        Historical bug: increment_uploads created entries keyed by GUID
        while mark_collection_stale/fresh used DB integer ID.
        This cleans up the orphaned DB-ID-keyed entries.
        """
        guid_key = collection.collection_id
        for key in list(states.keys()):
            if key == guid_key:
                continue
            state = states.get(key)
            if state and state.get("collection_id") == guid_key:
                del states[key]
                logger.info(
                    "Removed duplicate maintenance state key=%s for collection %s",
                    key,
                    guid_key,
                )

    def _load_states(self) -> dict[str, dict[str, Any]]:
        """Return cached state, loading from disk only on first access (PE1)."""
        if self._cache is not None:
            return self._cache
        if not os.path.exists(self._path):
            self._cache = {}
            return self._cache
        try:
            with open(self._path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Failed to load maintenance state from %s: %s", self._path, exc
            )
            self._cache = {}
            return self._cache
        if not isinstance(data, dict):
            self._cache = {}
            return self._cache
        self._cache = data
        return self._cache

    def _save_states(self, states: dict[str, dict[str, Any]]) -> None:
        self._cache = states  # keep cache in sync with what we persist
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp_path = f"{self._path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(states, handle, indent=2)
        os.replace(tmp_path, self._path)
