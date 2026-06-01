"""Shared ID parsing from LLM responses."""

import re


def parse_ids(response: str, valid_ids: list[int]) -> list[int]:
    """Parse comma-separated IDs from LLM response, validate against *valid_ids*."""
    numbers = re.findall(r"\d+", response)
    if not numbers:
        return valid_ids

    selected = []
    for num_str in numbers:
        try:
            num = int(num_str)
            if num in valid_ids:
                selected.append(num)
        except ValueError:
            continue

    return selected or valid_ids
