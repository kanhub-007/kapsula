# Domain Model — Search Result DTOs

All DTOs are pure dataclasses in `core/application/dto/`. None are
persisted; none depend on Pydantic or FastAPI.

## `SearchHit`
| Field | Type | Notes |
|-------|------|-------|
| `index` | `int` | chunk index |
| `content` | `str` | raw chunk content |
| `expanded_content` | `str \| None` | set by context expansion |
| `score` | `float` | fused/final score |
| `dense_score` | `float` | |
| `sparse_score` | `float` | |
| `rerank_score` | `float \| None` | only when reranked |
| `retrieval_score` | `float \| None` | |
| `sub_document_id` | `int \| None` | |
| `sub_document_key` | `str \| None` | |
| `collection_id` | `int \| None` | |
| `collection_name` | `str \| None` | |
| `document_id` | `int \| None` | |
| `document_filename` | `str \| None` | |
| `parent_hash` | `str \| None` | |
| `contributing_chunks` | `list[int] \| None` | |
| `collection_route_confidence` | `float \| None` | |
| `subdocument_route_confidence` | `float \| None` | |
| `metadata_route_confidence` | `float \| None` | |

Lives in `core/application/dto/search_hit.py`.

## `SubAnswer`
| Field | Type |
|-------|------|
| `question` | `str` |
| `answer` | `str` |
| `has_answer` | `bool` |
| `num_results` | `int` |
| `search_results` | `list[SearchHit]` |

Lives in `core/application/dto/sub_answer.py`.

## `SearchPlan`
| Field | Type |
|-------|------|
| `strategy` | `str` |
| `queries` | `list[str]` |
| `reasoning` | `str` |
| `total_unique_results` | `int \| None` |
| `sub_answers_count` | `int \| None` |

Lives in `core/application/dto/search_plan.py`.

## `IntelligentSearchResult`
| Field | Type |
|-------|------|
| `answer` | `str \| None` |
| `has_answer` | `bool` |
| `relevant_results` | `list[int]` |
| `total_evaluated` | `int` |
| `search_results` | `list[SearchHit]` |
| `plan` | `SearchPlan \| None` |
| `sub_answers` | `list[SubAnswer] \| None` |
| `error` | `str \| None` |

Lives in `core/application/dto/intelligent_search_result.py`.

## Mappers
| Mapper | Location | Direction |
|--------|----------|-----------|
| `hit_from_dict(d) -> SearchHit` | `core/application/dto/search_hit.py` (classmethod) | internal dict → DTO (used where retrievers still emit dicts) |
| `to_search_result(hit, citation) -> SearchResult` | `presentation/api/search_presenter.py` | DTO → Pydantic (API) |
| `format_search_results(query, hits, ...)` | `presentation/mcp/search_presenter.py` | DTO → text (MCP) |

## Streaming serialization
The streaming route serializes the DTO with `dataclasses.asdict(result)`
so SSE consumers see the same JSON keys they do today. The
citation-augmentation step reads typed DTO fields, adds citations, then
re-serializes.

## Architecture decision
DTOs are application-layer types, not domain entities — they exist only
to cross the application→presentation boundary and carry no domain
behaviour. Presenters (presentation layer) own the DTO→wire mapping, so
Pydantic/FastAPI concerns stay out of the application layer.
