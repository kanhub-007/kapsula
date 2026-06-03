"""
Breadcrumb parser for extracting hierarchical document structure from H1 headers.
"""

import re
import logging
from typing import Dict, List, Any
import hashlib

logger = logging.getLogger(__name__)


def parse_breadcrumb(header: str) -> Dict[str, Any]:
    """
    Parse H1 breadcrumb header.

    Examples:
        "# docs.example.com / Guides / API Reference / Authentication"
        → {"domain": "docs.example.com", "levels": ["Guides", "API Reference", "Authentication"]}

    Args:
        header: H1 header line (with or without leading #)

    Returns:
        {
            "domain": str,
            "levels": List[str],
            "breadcrumb_key": str,  # Index 2 or max level
            "full_path": str,
            "raw": str
        }
    """
    # Remove leading # and whitespace
    clean_header = header.strip()
    if clean_header.startswith("#"):
        clean_header = clean_header[1:].strip()

    # Split by /
    parts = [part.strip() for part in clean_header.split("/")]

    if len(parts) == 0:
        logger.warning(f"Empty breadcrumb header: {header}")
        return {
            "domain": "",
            "levels": [],
            "breadcrumb_key": "unknown",
            "full_path": clean_header,
            "raw": header,
        }

    # First part is typically the domain
    domain = parts[0] if len(parts) > 0 else ""
    levels = parts[1:] if len(parts) > 1 else parts

    # Breadcrumb key is index 2 (third part after domain), or max level if shorter
    if len(levels) >= 2:
        breadcrumb_key = levels[1]  # Index 2 overall (domain, level[0], level[1])
    elif len(levels) == 1:
        breadcrumb_key = levels[0]
    else:
        breadcrumb_key = domain

    return {
        "domain": domain,
        "levels": levels,
        "breadcrumb_key": breadcrumb_key,
        "full_path": clean_header,
        "raw": header,
    }


def extract_subdocuments(markdown_content: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Split markdown into sub-documents based on breadcrumb structure.

    Groups pages by breadcrumb_key (index 2 of breadcrumb split).

    Args:
        markdown_content: Full markdown document

    Returns:
        {
            "About Hyperliquid": [
                {
                    "title": "Core Contributors",
                    "content": "...",
                    "breadcrumb": "...",
                    "breadcrumb_data": {...}
                },
                ...
            ],
            "For Developers": [...]
        }
    """
    subdocuments = {}
    lines = markdown_content.split("\n")

    current_page = None
    current_content_lines = []

    for line in lines:
        # Check if this is an H1 header
        h1_match = re.match(r"^#\s+(.+)$", line)

        if h1_match:
            # Save previous page if exists
            if current_page:
                current_page["content"] = "\n".join(current_content_lines).strip()

                # Add to subdocument
                key = current_page["breadcrumb_data"]["breadcrumb_key"]
                if key not in subdocuments:
                    subdocuments[key] = []
                subdocuments[key].append(current_page)

            # Start new page
            breadcrumb_data = parse_breadcrumb(line)

            # Get page title (last part of breadcrumb)
            page_title = (
                breadcrumb_data["levels"][-1]
                if breadcrumb_data["levels"]
                else breadcrumb_data["domain"]
            )

            current_page = {
                "title": page_title,
                "breadcrumb": breadcrumb_data["full_path"],
                "breadcrumb_data": breadcrumb_data,
                "content": "",
            }
            current_content_lines = [line]  # Include the header in content

        else:
            # Accumulate content for current page
            if current_page:
                current_content_lines.append(line)

    # Save last page
    if current_page:
        current_page["content"] = "\n".join(current_content_lines).strip()
        key = current_page["breadcrumb_data"]["breadcrumb_key"]
        if key not in subdocuments:
            subdocuments[key] = []
        subdocuments[key].append(current_page)

    logger.info(f"Extracted {len(subdocuments)} sub-documents from markdown")
    for key, pages in subdocuments.items():
        logger.info(f"  Sub-document '{key}': {len(pages)} pages")

    return subdocuments


def generate_content_hash(content: str) -> str:
    """Generate SHA256 hash of content for deduplication."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def validate_subdocuments(subdocuments: Dict[str, List[Dict[str, Any]]]) -> bool:
    """
    Validate that subdocuments have valid structure.

    Returns:
        True if valid, False otherwise
    """
    if not subdocuments:
        logger.warning("No subdocuments found")
        return False

    total_pages = sum(len(pages) for pages in subdocuments.values())
    if total_pages == 0:
        logger.warning("No pages found in subdocuments")
        return False

    logger.info(
        f"Validation: {len(subdocuments)} sub-documents, {total_pages} total pages"
    )
    return True
