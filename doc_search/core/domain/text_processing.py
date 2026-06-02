"""Text processing utilities shared by indexer and searcher."""

import re
from typing import List

_STEM_CACHE: dict[str, str] = {}


def simple_stem(word: str) -> str:
    """Apply simple stemming to improve BM25 matching."""
    if word in _STEM_CACHE:
        return _STEM_CACHE[word]

    original = word
    word_lower = word.lower()

    if len(word_lower) <= 3:
        _STEM_CACHE[original] = word_lower
        return word_lower

    if word_lower.endswith("ies") and len(word_lower) > 4:
        stemmed = word_lower[:-3] + "y"
    elif word_lower.endswith("es") and len(word_lower) > 3:
        stemmed = word_lower[:-2]
    elif word_lower.endswith("s") and len(word_lower) > 2:
        stemmed = word_lower[:-1]
    elif word_lower.endswith("ed") and len(word_lower) > 3:
        stemmed = (
            word_lower[:-2] if word_lower[-3] != word_lower[-4] else word_lower[:-1]
        )
    elif word_lower.endswith("ing") and len(word_lower) > 4:
        stemmed = word_lower[:-3]
    else:
        stemmed = word_lower

    _STEM_CACHE[original] = stemmed
    return stemmed


def tokenize(text: str) -> List[str]:
    """Tokenize text for BM25 indexing and search."""
    words = re.findall(r"\b\w+\b", text.lower())
    return [simple_stem(w) for w in words]


def is_meaningful_chunk(content: str, min_words: int = 5) -> bool:
    """Check if a chunk contains meaningful content."""
    text = content.strip()

    if len(text) < 50:
        return False

    words = re.findall(r"\b\w{2,}\b", text)
    return len(words) >= min_words
