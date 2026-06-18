# Spec Index — Deferred Code Review Items

## Implementation Order (Dependency Graph)

```
Spec 5 (fix-repository-temporal-coupling)  ← MUST BE FIRST
  │  Changes save_document return type
  │
  ├── Spec 2 (wire-upload-usecase)  ← depends on Spec 5
  │     Uses save_document, must capture return value
  │
  ├── Spec 1 (split-tasks-pipeline)  ← independent
  │     No dependency on other specs
  │
  ├── Spec 3 (consolidate-document-structure)  ← independent, but easier after Spec 1 & 4
  │     Migrates call sites that exist in files touched by Spec 4
  │
  └── Spec 4 (split-search-routes)  ← independent, but easier after Spec 3
        Splitting files that Spec 3 modifies
```

**Recommended execution order:** 5 → 2 → 1 → 3 → 4

## Spec Summaries

| # | Folder | What it does | Lines saved | Risk |
|---|--------|-------------|-------------|------|
| 5 | `fix-repository-temporal-coupling` | `save()` returns entity copy instead of mutating input | N/A (correctness) | Medium — signature changes across 4 repos |
| 2 | `wire-upload-usecase` | Route delegates to `UploadDocumentUseCase` | ~50 lines in route | Medium — changes upload path |
| 1 | `split-tasks-pipeline` | 1400-line God File → 8 focused modules | ~1000 lines extracted | High — background processing pipeline |
| 3 | `consolidate-document-structure` | 5 duplicate code blocks → 1 shared helper | ~150 lines removed | Low — pure consolidation |
| 4 | `split-search-routes` | 1200+775 line files → 7 sub-modules | N/A (reorganization) | Medium — many imports to update |

## Verification After Each Spec

After implementing any spec, run:
```bash
# 1. Lint
python -m ruff check kapsula/

# 2. Import check
python -c "from kapsula.startup.api import app; print('API OK')"
python -c "from kapsula.startup.mcp import create_server; print('MCP OK')"

# 3. Tests
python -m pytest tests/ -v

# 4. (If available) Integration smoke test
python -m pytest tests/test_mcp/test_integration.py -v
```

## Files Touched Per Spec

So you know what to check in git diff:

| Spec | Files created | Files modified |
|------|--------------|----------------|
| 5 | 0 | 6 (3 interfaces, 1 doc repo, 1 use case, 1 search data access) |
| 2 | 0 | 2 (use case + route) |
| 1 | 6-8 | 3 (tasks.py, routes/documents.py, startup/) |
| 3 | 0 | 3 (shared builder, routes/search.py, mcp/tools/search.py) |
| 4 | 6-7 | 3 (__init__.py files, old search.py) |
