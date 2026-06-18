"""JSON parsing utilities for LLM output."""

import re


def _parse_json_safely(text: str) -> dict:
    """Robust JSON parsing from LLM output — handles code fences and prose."""
    if not text:
        raise ValueError("No text to parse")

    s = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", s, re.IGNORECASE)
    if m:
        s = m.group(1).strip()
    else:
        s = s.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    if not (s.startswith("{") and s.endswith("}")):
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end != -1 and end > start:
            s = s[start : end + 1]

    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2018", "'").replace("\u2019", "'")

    # First attempt: direct parse
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    # Second attempt: fix trailing commas (common LLM mistake)
    try:
        fixed = re.sub(r',\s*([}\]])', r'\1', s)
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Third attempt: try to extract just the first valid JSON object
    try:
        decoder = json.JSONDecoder()
        obj, _idx = decoder.raw_decode(s)
        return obj
    except json.JSONDecodeError:
        pass

    # Give up — return empty dict so callers don't crash
    logger.warning("Failed to parse JSON from LLM output (length=%d): %.200s", len(s), s)
    return {}


