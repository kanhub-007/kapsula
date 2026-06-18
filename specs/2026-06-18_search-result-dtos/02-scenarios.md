# Scenarios — Search Result DTOs

---

## Slice 1 — `SearchHit` DTO

### Scenario S1.1: `MultiIndexSearcher` returns `list[SearchHit]`
**Priority:** Must
**Closes:** P7 (retrieval path)

**Gherkin:**
  Given `MultiIndexSearcher.search_subdocuments / search_single_index / search_collections`
  When  they return
  Then  the return type is `list[SearchHit]` (not `list[dict]`)
  And   every result is a `SearchHit` instance with typed fields

**Verify:** type annotations on the three methods; `isinstance(results[0], SearchHit)` in a test.

### Scenario S1.2: API presenter maps `SearchHit` → `SearchResult` (Pydantic)
**Priority:** Must

**Gherkin:**
  Given a `SearchHit`
  When  the API presenter formats it
  Then  `to_search_result(hit, citation)` reads typed attributes (no `hit["index"]`)
  And   the wire `SearchResult` JSON is byte-identical to before

**Verify:** snapshot/golden test on a representative search response; diff vs pre-refactor == none.

### Scenario S1.3: MCP presenter maps `SearchHit` → text
**Priority:** Must

**Gherkin:**
  Given `format_search_results(query, hits, ...)`
  When  called with `list[SearchHit]`
  Then  it reads `hit.score`, `hit.content`, `hit.sub_document_key`, etc. (attributes, not keys)
  And   the formatted text is unchanged

**Verify:** existing integration assertions on MCP search output stay green.

### Scenario S1.4: Route-confidence fields are optional on the DTO
**Priority:** Should

**Gherkin:**
  Given a subdocument-search hit (no collection routing)
  When  mapped to `SearchHit`
  Then  `collection_route_confidence` is `None` (not missing-key crash)
  And   the presenter treats `None` as "not reported"

---

## Slice 2 — `IntelligentSearchResult` + `SubAnswer` + `SearchPlan`

### Scenario S2.1: `IntelligentSearcher` returns `IntelligentSearchResult`
**Priority:** Must
**Closes:** P7 (intelligent path)

**Gherkin:**
  Given `evaluate_and_answer` / `evaluate_and_answer_with_planning*`
  When  they return
  Then  the return type is `IntelligentSearchResult` with typed fields
  And   `sub_answers: list[SubAnswer] | None`, `plan: SearchPlan | None`

**Verify:** type annotations; constructor fills every field.

### Scenario S2.2: No-results and error paths return well-formed DTOs
**Priority:** Must

**Gherkin:**
  Given empty search results
  When  `evaluate_and_answer` runs
  Then  the DTO has `has_answer=False`, `answer="No search results..."`, `total_evaluated=0`
  Given a chat-client failure
  When  `evaluate_and_answer` runs
  Then  the DTO has `has_answer=False` and `error` set (no exception escapes)

**Verify:** existing `test_intelligent_searcher.py` cases, retargeted to DTO field access.

### Scenario S2.3: Streaming `final_answer` event carries the DTO (serialized)
**Priority:** Must

**Gherkin:**
  Given the streaming endpoint
  When  it yields `final_answer`
  Then  the event `data` is the DTO serialized to a dict (`dataclasses.asdict`)
  And   the citation-augmentation step in the route reads typed fields before re-serializing

**Verify:** streaming test asserts the event payload keys are the DTO field names.

### Scenario S2.4: API route maps DTO → response models (no splat)
**Priority:** Must
**Closes:** the `SubAnswer(**sub_answer)` unvalidated splat

**Gherkin:**
  Given an `IntelligentSearchResult`
  When  the API route builds the response
  Then  it constructs `SearchPlan`, `SubAnswer`, `IntelligentCollectionSearchResponse` by explicit field mapping (no `**result` splat)
  And   the response JSON is unchanged

**Verify:** `grep "\*\*.*result\|\*\*sub_answer\|\*\*plan" kapsula/presentation/` returns nothing.

---

## Cross-cutting verify (every slice)
- `pytest tests/ -q` → all green (HF-network test excepted).
- `ruff check` + `black --check` → clean.
- `grep -rn '\["index"\]\|\.get("score"\|\.get("content"' kapsula/presentation/ kapsula/core/application/use_cases/` →
  only inside DTO mappers, never in route/presenter logic.
- Golden response snapshot unchanged vs pre-refactor.
