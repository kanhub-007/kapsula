"""Match chunk header breadcrumbs to parent section hashes.

Extracted from ``presentation/api/tasks.py`` into the chunking infrastructure
where it belongs — it operates on parent-section data (chunking output).
"""

from __future__ import annotations

from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


def match_header_to_parents(header: str, parent_sections: dict) -> dict:
    """Match a chunk's header breadcrumb to parent section hashes.

    Args:
        header: Breadcrumb path like ``"API > Auth > Parameters"``.
        parent_sections: Dict mapping doc-id hashes to parent section data
            (each has ``title``, ``level`` keys).

    Returns:
        Dict with keys ``immediate`` (H3), ``chapter`` (H2), ``page`` (H1).
        Falls back to parent level if a more specific level is not found.

    Note: Level mapping is H1=level_1, H2=level_2, H3=level_3.
    Context modes: "narrow" uses H3 (immediate), "deep" uses H2 (chapter).
    """
    # Split header into parts
    parts = [p.strip() for p in header.split(">")]

    # Initialize with None
    parents: dict[str, str | None] = {"immediate": None, "chapter": None, "page": None}

    # Track matches for debugging
    matched_titles: list[str] = []

    # Match parts to parent sections by title (case-insensitive partial matching)
    for doc_id, section in parent_sections.items():
        title = section["title"]
        level = section["level"]

        # Check if title matches any part of the breadcrumb (case-insensitive)
        title_lower = title.lower()
        for part in parts:
            part_lower = part.lower()

            # Exact match or partial match (title contains part or part contains title)
            if (
                title_lower == part_lower
                or title_lower in part_lower
                or part_lower in title_lower
            ):
                # H3 is the most granular (immediate context for narrow mode)
                if level == "level_3":
                    parents["immediate"] = doc_id
                    matched_titles.append(f"immediate(H3)='{title}'")
                # H2 is chapter level (deep context mode)
                elif level == "level_2":
                    parents["chapter"] = doc_id
                    matched_titles.append(f"chapter(H2)='{title}'")
                # H1 is page level (broadest context)
                elif level == "level_1":
                    parents["page"] = doc_id
                    matched_titles.append(f"page(H1)='{title}'")
                break  # Found a match for this section, move to next

    # Log matches for debugging
    if matched_titles:
        logger.debug("Matched header '%s' to: %s", header, ", ".join(matched_titles))
    else:
        logger.warning("No parent matches found for header '%s'", header)

    # Fallback hierarchy: narrow mode (immediate) <- chapter <- page
    # If immediate (H3) not found, try using chapter (H2)
    if not parents["immediate"] and parents["chapter"]:
        parents["immediate"] = parents["chapter"]
        logger.debug(
            "No H3 immediate found for '%s', using H2 chapter as fallback", header
        )

    # If chapter (H2) not found, try using page (H1)
    if not parents["chapter"] and parents["page"]:
        parents["chapter"] = parents["page"]
        logger.debug("No H2 chapter found for '%s', using H1 page as fallback", header)

    # If page (H1) not found, use whatever we have
    if not parents["page"]:
        if parents["chapter"]:
            parents["page"] = parents["chapter"]
        elif parents["immediate"]:
            parents["page"] = parents["immediate"]

    # Log final result
    has_any = any(v is not None for v in parents.values())
    if not has_any:
        logger.error(
            "Failed to find ANY parent for header '%s' - context expansion will fail!",
            header,
        )

    return parents
