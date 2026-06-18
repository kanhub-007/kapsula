# Domain Model — Async Collection Maintenance

## Entities

### MaintenanceJob
| Field | Type | Description |
|-------|------|-------------|
| job_id | str (GUID) | Unique identifier for this maintenance run |
| collection_id | str (GUID) | The collection being maintained |
| status | str | One of: queued, running, completed, failed |
| stage | str | Current processing stage: summarizing, indexing, consolidating, completed |
| progress | str | Human-readable progress description |
| summary_updates | int | Number of document summaries updated (populated on completion) |
| summary_failures | int | Number of document summaries that failed |
| collection_faiss | str \| None | Path to rebuilt collection FAISS index |
| collection_bm25 | str \| None | Path to rebuilt collection BM25 index |
| account_faiss | str \| None | Path to rebuilt account FAISS index |
| account_bm25 | str \| None | Path to rebuilt account BM25 index |
| cards_created | int | Consolidation topic/evolution/gap cards created |
| cards_updated | int | Consolidation cards updated |
| error | str \| None | Error message if status is "failed" |
| created_at | datetime | When the job was created |
| updated_at | datetime | When the job was last updated |

**Persisted?** Yes — in-memory dict (matching SearchJob pattern), not a DB table. Rationale: maintenance jobs are short-lived (minutes, not hours), don't need to survive server restarts, and the SearchJob pattern is already proven in the codebase.

### Interfaces (for DI)

No new interfaces needed. The existing `BackgroundProcessor` interface is for document uploads and uses a different signature. Maintenance uses the `SearchJob` / `SearchJobManager` pattern directly.

### Existing Components Reused

| Component | Path | Role |
|-----------|------|------|
| `ThreadPoolBackgroundProcessor` | `infrastructure/repositories/processing/` | Starts daemon thread for background work |
| `MaintenanceStateManager` | `presentation/upload/` | Tracks stale/fresh state (already used by sync runner) |
| `CollectionMaintenanceRunner` | `presentation/upload/` | The actual maintenance logic — will be called from background thread |

### New Components

| Component | Path | Role |
|-----------|------|------|
| `MaintenanceJob` | `presentation/mcp/maintenance_job.py` | Simple dataclass for job state |
| `MaintenanceJobManager` | `presentation/mcp/maintenance_job_manager.py` | In-memory job lifecycle management (mirrors SearchJobManager) |
| `run_collection_maintenance` (modified) | `presentation/mcp/tools/collections.py` | Now async: creates job, starts thread, returns job_id |
| `get_maintenance_job` (new tool) | `presentation/mcp/tools/collections.py` | Polls job by job_id |
| `get_collection_maintenance_status` (new tool) | `presentation/mcp/tools/collections.py` | Shows latest job for a collection (Slice 2) |

### Entity vs ORM Separation
- `MaintenanceJob` is a plain dataclass with no framework dependencies — stored in memory via `MaintenanceJobManager`, not in SQLite
- No ORM model needed (unlike `upload_jobs` which uses `UploadJob` ORM table)
- Rationale: maintenance jobs are transient; the SearchJob pattern (in-memory) is the right fit
