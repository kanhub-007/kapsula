# Comprehensive Code-Review Fixes

## User Story
As a maintainer of kapsula, I want every finding from the 2026-06-18
comprehensive code review fixed, so that the codebase conforms to its own
Clean-Architecture + 21-pattern constitution across all dimensions
(architecture, patterns, SOLID, DRY, structure, conventions, logic,
security, performance, tests) and the highest-risk orchestration paths
are covered by tests.

## Context

A full review of `kapsula/` (~17.5k LOC across five layers) surfaced 46
findings. The most dangerous are:

- **L1 (Critical)** — the HTTP upload route dispatches background
  processing *twice* (once via `UploadDocumentUseCase` →
  `BackgroundProcessor`, once via `BackgroundTasks.add_task`), causing
  duplicate chunks, duplicate index files, and races on shared state.
- **L2 (High)** — the streaming intelligent-search handler yields an
  error event but does not `return`, then dereferences an unbound
  `search_plan` → `UnboundLocalError` → a second error event.
- **T1 (Critical)** — the four most complex classes
  (`HybridSearcher`, `IntelligentSearcher`, `MultiIndexSearcher`,
  `ConsolidationRunner`) and the 866-line `tasks.py` have **zero**
  behavioural tests. L1 and L2 survived precisely because of this.

The remainder are architectural debt (`SearchDataAccess` leaks ORM,
`ConsolidationRunner` writes inline bypassing repositories,
`MaintenanceStateManager()` constructed at 9 call sites), pattern smells
(anemic ingestion "strategies", duplicated streaming/non-streaming
methods, God Methods in `tasks.py`), DRY violations (underscore-prefixed
helpers imported cross-module, duplicated `_prepare_intelligent_search`
between API and MCP), and a handful of security/perf/convention nits
(timing-unsafe API-key compare, `pickle.load` on BM25 files, N+1 in
`list_accounts`, cryptic handler names, missing type annotations).

All fixes must preserve the existing 120-test green baseline and the
public API/MCP tool contracts.

## Non-Goals
- Changing any external HTTP or MCP tool contract (request/response
  shapes, tool names, descriptions).
- Changing the on-disk FAISS index format (only the BM25 serialisation
  changes, and only to a safer loader — old files remain readable).
- Multi-tenant IDOR authorisation (SE3) — tracked as a separate future
  spec; this work only adds the constant-time compare (SE1) and removes
  `pickle` RCE risk (SE2).
- Replacing SQLite or the `processing_status` in-memory store with a
  different technology — only DI/caching is improved.
- Performance work beyond the three flagged items (PE1–PE3).

## Slices

- **Slice 1 — Critical correctness & security quick wins**
  (L1, L2, L3, L4, SE1, SE2, SC3, D3). Low-risk, high-impact, lands first.
- **Slice 2 — Tests for core orchestration**
  (T1.1–T1.5). Adds the missing behavioural tests; T1.5 (end-to-end
  upload) pins the L1 fix.
- **Slice 3 — Architecture debt**
  (A1, A2, A3, A4, A5, A6, O1, O2, O3, O4). The biggest structural
  changes; lands after tests exist to catch regressions.
- **Slice 4 — Patterns & SOLID**
  (P1–P8, S1–S4). Strategy, Template Method, DTOs, SRP splits.
- **Slice 5 — DRY, conventions, perf, remaining**
  (D1, D2, D4, D5, SC1–SC7, PE1–PE3, P5, P6). Cleanup pass; absorbs the
  remaining file-size and naming findings.

Each slice ends with the full suite green + `ruff check` + `black` clean.

## Out of Scope (explicitly deferred)
- SE3 (account-scoped IDOR authorisation) — needs its own spec.
- Full CQRS for reads — only the ORM leak in `SearchDataAccess` is fixed.
