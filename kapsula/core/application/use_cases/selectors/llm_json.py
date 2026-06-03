"""Shared LLM JSON response extraction utility."""

from __future__ import annotations

import json
import re
from typing import Any


def extract_json_object(response: str) -> dict[str, Any]:
    """Extract the first JSON object from an LLM response.

    Handles common LLM formatting like markdown code fences and
    explanatory text around the JSON payload.
    """
    text = _strip_code_fences(response.strip())
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end >= start:
        text = text[start : end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


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


def _strip_code_fences(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = [line for line in text.splitlines() if not _is_fence_line(line)]
    return "\n".join(lines).strip()


def _is_fence_line(line: str) -> bool:
    stripped = line.strip()
    return bool(re.match(r"^```", stripped))
