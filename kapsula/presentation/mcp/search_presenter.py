"""MCP-facing search result formatting."""


def format_search_results(query: str, results: list[dict], scope: str = "") -> str:
    """Format search results as compact plain text for MCP clients."""
    if not results:
        return "No results found."
    title_scope = f" {scope}" if scope else ""
    out = [f"Found {len(results)} results{title_scope} for: {query}\n"]
    for i, result in enumerate(results, 1):
        src = result.get("collection_name", "?")
        doc = result.get("document_filename", "?")
        score = result.get("rerank_score") or result.get("score", 0)
        content = result.get("expanded_content", result.get("content", ""))
        out.append(f"--- Result {i} [{src}/{doc}] score={score:.3f} ---")
        out.append(content[:1500])
        out.append("")
    return "\n".join(out)
