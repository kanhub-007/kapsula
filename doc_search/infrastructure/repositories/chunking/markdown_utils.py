"""Markdown utility functions."""

import re
from typing import List
import tiktoken


def clean_markdown_link(text: str) -> str:
    text = re.sub(r"\[([^\]]*)\]\([^\)]*\)", r"\1", text)
    text = re.sub(r"^\[\]\([^\)]*\)", "", text)
    text = re.sub(r"\*\*([^\*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^\*]+)\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    return text.strip()


def split_breadcrumb_title(text: str) -> List[str]:
    parts = [part.strip() for part in text.split("/")]
    return [p for p in parts if p]


def count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    encoding = tiktoken.get_encoding(encoding_name)
    return len(encoding.encode(text))
