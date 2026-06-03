"""Markdown formatting normalisation and chunk-to-source position matching.

When ``unstructured`` parses markdown, its ``str(el)`` strips inline formatting
markers (``**bold**``, ``*italic*``, ``>`` blockquote prefixes, list markers).
This means chunk content produced by ``MarkdownChunker`` does not literally
appear in the raw markdown source.  These utilities normalise the raw source
so chunk text can be located for citation metadata.
"""

import re


def strip_inline_formatting(text: str) -> str:
    """Strip markdown inline formatting that ``unstructured`` removes from str(el)."""
    # Bold / italic (**bold**, __bold__, *italic*, _italic_)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"\1", text)
    # Inline code (`code`)
    text = re.sub(r"`(.+?)`", r"\1", text)
    # Strikethrough (~~text~~)
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    # Blockquote prefix (> at line start)
    text = re.sub(r"^> ?", "", text, flags=re.MULTILINE)
    # Unordered list markers (- or * at line start, or inline between joined items)
    text = re.sub(r"^(?:- |\* )(.*)$", r"\1", text, flags=re.MULTILINE)
    # Inline list markers — when items are joined on one line: "... - item ..."
    text = re.sub(r"(?<=\S) (?:- |\* )(?=\S)", " ", text)
    # Ordered list markers (1. 2. etc at line start)
    text = re.sub(r"^\d+\.\s+(.*)$", r"\1", text, flags=re.MULTILINE)
    # Collapse newlines and multiple spaces (after line-start patterns applied)
    text = re.sub(r"\n+", " ", text)
    text = re.sub(r" +", " ", text)
    return text


def find_chunk_in_markdown(
    search_text: str, markdown_content: str
) -> int:
    """Find chunk text position with progressive fallbacks for formatting.

    Returns the character offset in *markdown_content* where *search_text*
    begins, or -1 if no match is found.
    """
    # 1) Direct exact match
    pos = markdown_content.find(search_text)
    if pos != -1:
        return pos

    # 2) Match against formatting-stripped markdown
    stripped_md = strip_inline_formatting(markdown_content)
    stripped_search = strip_inline_formatting(search_text)
    pos = stripped_md.find(stripped_search)
    if pos == -1:
        # 3) Progressive shortening on stripped text
        for length in range(len(stripped_search) - 10, 29, -5):
            shorter = stripped_search[:length].strip()
            pos = stripped_md.find(shorter)
            if pos != -1:
                break

    if pos != -1:
        # Map back from stripped position to raw position
        return _map_stripped_to_raw(stripped_md, pos, markdown_content)

    return -1


def _map_stripped_to_raw(
    stripped_md: str, stripped_pos: int, raw_content: str
) -> int:
    """Map a character position in stripped markdown back to raw markdown.

    The stripped version may have newlines and multiple spaces collapsed,
    so we skip past those in the raw content while advancing through stripped."""
    raw_pos = 0
    stripped_i = 0
    while stripped_i < stripped_pos and raw_pos < len(raw_content):
        sc = stripped_md[stripped_i]
        rc = raw_content[raw_pos]
        if sc == rc:
            stripped_i += 1
            raw_pos += 1
        elif rc in ("\n", "\r", " ", "\t") and stripped_md[stripped_i - 1:stripped_i + 1] != rc:
            # Skip whitespace in raw that was collapsed in stripped
            raw_pos += 1
        else:
            raw_pos += 1
    return raw_pos
