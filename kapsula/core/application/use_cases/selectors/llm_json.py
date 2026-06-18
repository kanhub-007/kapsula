"""Typed extractors for LLM JSON responses.

JSON parsing itself lives in :mod:`kapsula.core.domain.json_utils` (single
source of truth). This module adds typed, key-level accessors on top of the
parsed dict.
"""

from __future__ import annotations

from typing import Any

from kapsula.core.domain.json_utils import _parse_json_safely


def extract_json_object(response: str) -> dict[str, Any]:
    """Extract the first JSON object from an LLM response.

    Delegates to ``_parse_json_safely`` so all LLM-output quirks (code fences,
    prose wrapping, trailing commas, curly quotes) are handled in one place.
    """
    return _parse_json_safely(response)


def extract_json_float(
    payload: dict[str, Any], key: str, default: float = 0.0
) -> float:
    try:
        return max(0.0, min(1.0, float(payload.get(key, default))))
    except (TypeError, ValueError):
        return default


def extract_json_int(payload: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(payload.get(key, default))
    except (TypeError, ValueError):
        return default


def extract_json_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    items = payload.get(key, [])
    return items if isinstance(items, list) else []
