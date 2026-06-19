"""Search result hit — the canonical typed shape for one retrieved chunk.

Closes H4 (primitive obsession): the search pipeline previously passed
``list[dict[str, Any]]`` everywhere, so the result shape (which fields
exist, what they mean) was implicit and every consumer used
``.get(key, default)`` defensively. This dataclass names the contract once.

Fields are populated incrementally as a hit flows through the pipeline:

* retriever → ``index``, ``content``, ``original_rank`` (dropped after fusion),
  ``dense_score`` / ``sparse_score``
* fusion → ``score`` (combined), finalised ``dense_score`` / ``sparse_score``
* reranker (optional) → ``rerank_score``
* :class:`MultiIndexSearcher` → ``collection_*``, ``document_*``,
  ``sub_document_*``, ``*_route_confidence`` provenance fields
* :func:`expand_context_with_parents` → ``expanded_content``, ``parent_hash``,
  ``contributing_chunks`` / ``contributing_scores``, ``context_mode``

Stages that haven't run yet leave the later fields at their defaults (None /
0.0). Use :meth:`from_dict` / :meth:`as_dict` to cross the dict boundary at
infrastructure seams (retrievers, fusion still emit dicts internally).
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any


@dataclass
class SearchResultHit:
    """One retrieved, fused, routed, and optionally context-expanded chunk."""

    # ── identity + content (populated by the retriever) ───────────────
    index: int
    content: str

    # ── scores (populated by fusion / reranker) ───────────────────────
    score: float = 0.0
    dense_score: float = 0.0
    sparse_score: float = 0.0
    rerank_score: float | None = None
    retrieval_score: float | None = None

    # ── context expansion (populated by expand_context_with_parents) ──
    expanded_content: str | None = None
    context_mode: str | None = None
    parent_hash: str | None = None
    chunk_content: str | None = None
    contributing_chunks: list[int] | None = None
    contributing_scores: list[float] | None = None

    # ── provenance: where this hit came from (MultiIndexSearcher) ─────
    collection_id: int | None = None
    collection_name: str | None = None
    collection_route_confidence: float | None = None
    collection_route_reason: str | None = None
    document_id: int | None = None
    document_filename: str | None = None
    sub_document_id: int | None = None
    sub_document_key: str | None = None

    # ── routing confidence / weights ──────────────────────────────────
    subdocument_route_confidence: float | None = None
    subdocument_route_reason: str | None = None
    metadata_route_confidence: float | None = None
    metadata_score: float | None = None
    route_weight: float | None = None

    # ── dict boundary helpers ─────────────────────────────────────────

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SearchResultHit:
        """Build a hit from a result dict, ignoring unknown keys.

        Used at infrastructure seams (retriever/fusion output) so the typed
        contract starts the moment a dict enters the application layer.
        """
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known and v is not None}
        # ``index`` and ``content`` are required; default sensibly if absent
        # so a malformed dict degrades to an empty hit rather than raising.
        kwargs.setdefault("index", data.get("index", -1))
        kwargs.setdefault("content", data.get("content", ""))
        return cls(**kwargs)

    def as_dict(self) -> dict[str, Any]:
        """Emit the full result dict (mirrors the legacy ``dict`` shape).

        Presenters and any remaining dict consumers use this. Includes only
        non-default fields so callers get the same sparse shape they had
        before (no wave of ``None`` keys in API responses).
        """
        result: dict[str, Any] = {
            "index": self.index,
            "content": self.content,
            "score": self.score,
            "dense_score": self.dense_score,
            "sparse_score": self.sparse_score,
        }
        optional = {
            "rerank_score": self.rerank_score,
            "retrieval_score": self.retrieval_score,
            "expanded_content": self.expanded_content,
            "context_mode": self.context_mode,
            "parent_hash": self.parent_hash,
            "chunk_content": self.chunk_content,
            "contributing_chunks": self.contributing_chunks,
            "contributing_scores": self.contributing_scores,
            "collection_id": self.collection_id,
            "collection_name": self.collection_name,
            "collection_route_confidence": self.collection_route_confidence,
            "collection_route_reason": self.collection_route_reason,
            "document_id": self.document_id,
            "document_filename": self.document_filename,
            "sub_document_id": self.sub_document_id,
            "sub_document_key": self.sub_document_key,
            "subdocument_route_confidence": self.subdocument_route_confidence,
            "subdocument_route_reason": self.subdocument_route_reason,
            "metadata_route_confidence": self.metadata_route_confidence,
            "metadata_score": self.metadata_score,
            "route_weight": self.route_weight,
        }
        result.update({k: v for k, v in optional.items() if v is not None})
        return result

    @staticmethod
    def from_dicts(items: list[dict[str, Any]]) -> list[SearchResultHit]:
        """Convert a list of result dicts to typed hits."""
        return [SearchResultHit.from_dict(d) for d in items]
