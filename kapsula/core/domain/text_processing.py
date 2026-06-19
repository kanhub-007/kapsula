"""Text processing utilities shared by indexer and searcher."""

import re
from functools import lru_cache


def parse_node_type_filter(node_type_filter: str | None) -> list[str] | None:
    """Parse a comma-separated node type filter string.

    Args:
        node_type_filter: Comma-separated string like ``"table,code"``.

    Returns:
        List of node type strings, or None if input is empty/None.
    """
    if not node_type_filter:
        return None
    parsed = [item.strip() for item in node_type_filter.split(",") if item.strip()]
    return parsed or None


@lru_cache(maxsize=100_000)
def _stem_inner(word: str) -> str:
    """Apply simple stemming to a single lower-cased word.

    Bounded via :func:`functools.lru_cache` so the cache cannot grow without
    limit (closes H4: was an unbounded module-level dict mutated from any
    thread without synchronisation). ``lru_cache`` is also thread-safe.
    """
    if len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        stemmed = word[:-3] + "y"
    elif word.endswith("es") and len(word) > 3:
        stemmed = word[:-2]
    elif word.endswith("s") and len(word) > 2:
        stemmed = word[:-1]
    elif word.endswith("ed") and len(word) > 3:
        stemmed = word[:-2] if word[-3] != word[-4] else word[:-1]
    elif word.endswith("ing") and len(word) > 4:
        stemmed = word[:-3]
    else:
        stemmed = word
    return stemmed


def simple_stem(word: str) -> str:
    """Apply simple stemming to improve BM25 matching."""
    # Lower-case once here so the cache key is canonical.
    return _stem_inner(word.lower())


def clear_stem_cache() -> None:
    """Clear the bounded stem cache (used by tests)."""
    _stem_inner.cache_clear()


def tokenize(text: str) -> list[str]:
    """Tokenize text for BM25 indexing and search."""
    words = re.findall(r"\b\w+\b", text.lower())
    return [simple_stem(w) for w in words]


def is_meaningful_chunk(content: str, min_words: int = 5) -> bool:
    """Check if a chunk contains meaningful content.

    A chunk is meaningful if it is at least 50 characters long and contains
    at least *min_words* words of 2+ characters.

    Args:
        content: Chunk text to evaluate.
        min_words: Minimum number of words required (default 5).

    Returns:
        True if the chunk passes both length and word-count thresholds.
    """
    text = content.strip()

    if len(text) < 50:
        return False

    words = re.findall(r"\b\w{2,}\b", text)
    return len(words) >= min_words
