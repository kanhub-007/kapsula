"""MCP-facing search result formatting."""

# Threshold for reporting a dense signal as present in the score breakdown.
# Must match the dense threshold in quality_filter.py (currently 0.15).
_DENSE_SIGNAL_THRESHOLD = 0.15


def format_search_results(
    query: str,
    results: list[dict],
    scope: str = "",
    context_mode: str = "none",
) -> str:
    """Format search results as self-documenting plain text for MCP clients.

    Each result includes: score breakdown (dense/sparse/fused), signal
    indicators, context mode, and source info — so the LLM can judge
    relevance without guessing.

    Args:
        query: Original search query.
        results: List of search result dicts with keys ``score``, ``content``, etc.
        scope: Optional scope label (e.g., ``"in collection 'Foo'"``).
        context_mode: Context expansion mode (``none``, ``narrow``, ``deep``).

    Returns:
        Formatted multi-line string suitable for LLM consumption.
    """
    """Format search results as self-documenting plain text for MCP clients.

    Each result includes: score breakdown (dense/sparse/fused), signal
    indicators, context mode, and source info — so the LLM can judge
    relevance without guessing.
    """
    if not results:
        return "No results found."

    title_scope = f" {scope}" if scope else ""
    out = [
        f"Found {len(results)} results{title_scope} for: {query}",
        f"context_mode: {context_mode} | scores: 0.0-1.0 (>0.5 good, >0.7 strong)",
        "",
    ]

    for i, result in enumerate(results, 1):
        src = result.get("collection_name", "?")
        doc = result.get("document_filename", "?")
        score = result.get("rerank_score") or result.get("score", 0)
        dense = result.get("dense_score")
        sparse = result.get("sparse_score")
        content = result.get("expanded_content", result.get("content", ""))
        result_context = result.get("context_mode", context_mode)

        # Score breakdown
        score_parts = [f"fused={score:.3f}"]
        if dense is not None:
            score_parts.append(f"dense={dense:.3f}")
        if sparse is not None:
            score_parts.append(f"sparse={sparse:.3f}")
        score_line = ", ".join(score_parts)

        # Signal indicator
        has_dense = dense is not None and dense > _DENSE_SIGNAL_THRESHOLD
        has_sparse = sparse is not None and sparse > 0.0
        if has_dense and has_sparse:
            signal = "both signals"
        elif has_dense:
            signal = "dense only"
        elif has_sparse:
            signal = "sparse only"
        else:
            signal = "weak"

        # Context mode label
        ctx_labels = {"none": "chunk", "narrow": "H3 section", "deep": "H2 chapter"}
        ctx_label = ctx_labels.get(result_context, result_context)

        sub_key = result.get("sub_document_key", "")
        sub_info = f" [{sub_key}]" if sub_key else ""

        out.append(f"--- Result {i} [{src}/{doc}]{sub_info} ---")
        out.append(f"  score: {score_line} ({signal}) | context: {ctx_label}")
        out.append(content[:1500])
        out.append("")

    return "\n".join(out)
