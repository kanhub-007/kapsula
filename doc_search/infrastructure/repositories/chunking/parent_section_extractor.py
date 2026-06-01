"""Parent section extraction with stable SHA256 hashes."""

import hashlib
import re
from typing import Dict

from doc_search.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


def extract_parent_sections(markdown_content: str) -> Dict[str, Dict[str, str]]:
    lines = markdown_content.split("\n")
    sections: dict = {}
    active: dict[int, dict | None] = {1: None, 2: None, 3: None}
    char_position = 0

    for line in lines:
        heading_match = re.match(r"^(#{1,3})\s+(.+)$", line.strip())

        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()

            if level == 1:
                for close_level in [1, 2, 3]:
                    if active[close_level]:
                        _close_section(sections, active, close_level, char_position)
            else:
                for close_level in range(level, 4):
                    if active[close_level]:
                        _close_section(sections, active, close_level, char_position)

            active[level] = {
                "title": title, "level": level,
                "content_lines": [], "start_char": char_position,
            }
        else:
            for lvl in [1, 2, 3]:
                if active[lvl]:
                    active[lvl]["content_lines"].append(line)

        char_position += len(line) + 1

    for lvl in [1, 2, 3]:
        if active[lvl]:
            _close_section(sections, active, lvl, char_position)

    return sections


def _close_section(
    sections: dict, active: dict, level: int, end_char: int
) -> None:
    data = active[level]
    content = "\n".join(data["content_lines"]).strip()
    hash_input = f"level_{data['level']}:{data['title']}".encode("utf-8")
    doc_id = hashlib.sha256(hash_input).hexdigest()
    sections[doc_id] = {
        "level": f"level_{data['level']}",
        "title": data["title"],
        "content": content,
        "start_char": data["start_char"],
        "end_char": end_char,
    }
    active[level] = None
