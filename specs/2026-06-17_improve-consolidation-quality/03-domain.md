# Domain Model — Improve Consolidation Quality

## Entities Affected

### LibraryCard (existing, modified)
The `LibraryCard` table already exists. Slice 1 changes no schema — it fixes how `content` and `importance` are populated. Slice 2 adds an optional `description` column.

| Field | Type | Current | After fix |
|-------|------|---------|-----------|
| `content` | Text | Raw section text (with image markdown for structural cards) | Structural cards: image markdown stripped from preview region |
| `importance` | Float | 0.0-1.0 in theory, but -1.0/-0.9 observed (LLM escape hatch) | Clamped to [0.0, 1.0]; prompt rewritten to ground the scale |
| `title` | String | Verbatim heading for structural; LLM-invented for topic | Topic: deduplicated via prompt (existing labels passed in) |
| `description` | String (NEW, Slice 2) | — | One-line LLM-generated description for terse structural titles |

### Importance Semantics (redesigned)

**Old definition (vague, broken):**
```
importance: 0.0-1.0. Use 0.9+ for critical facts, 0.5 for background, 0.3 for trivia.
```

**New definition (grounded, measurable):**
```
importance: 0.0-1.0. Rate how central this topic is to the collection's argument:
  1.0 = Foundational concept (the argument collapses without it; many other topics reference it)
  0.8 = Core mechanism (named institutions, specific processes, dates, or key actors)
  0.6 = Supporting evidence (case studies, examples, historical parallels)
  0.4 = Contextual background (definitions, framing, peripheral mentions)
Always return a value in [0.0, 1.0]. Never return negative values.
```

This grounds the scale in something the LLM can assess from the content itself, rather than the subjective "critical facts / trivia" framing that produced bimodal clustering and negative escape-hatch values.

### Interfaces (for DI)

No new interfaces. The fixes modify existing methods:
- `ConsolidationRunner._cluster_topics` — receives existing labels, prompt updated
- `ConsolidationRunner._generate_topic_card` — clamps importance, updated prompt
- Card generation in `tasks.py:915` — strips image markdown from structural card content

## Entity vs ORM Separation
- `LibraryCard` ORM model: `infrastructure/data/tables/library_card.py` — no change for Slice 1
- Slice 2 `description` column: add to the ORM model via Alembic migration (or `Base.metadata.create_all` if no migration tooling)
- No domain entity changes — `LibraryCard` is a persistence model, not a domain entity
