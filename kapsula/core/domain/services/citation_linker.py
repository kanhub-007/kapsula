"""Add citation triplet metadata to chunks before persistence."""

import logging
from typing import List, Dict, Any

from kapsula.core.domain.citation_matching import find_chunk_in_markdown

logger = logging.getLogger(__name__)


def add_citation_metadata_to_chunks(
    chunks: List[Dict[str, Any]],
    parent_sections: Dict[str, Dict[str, str]],
    markdown_content: str,
) -> List[Dict[str, Any]]:
    """
    Add citation triplet metadata to chunks before they're saved to database.

    For each chunk, finds the matching parent section and calculates:
    - library_card_doc_id: The doc_id (hash) of the parent section (to be resolved to library_card_id later)
    - start_char: Character position where chunk starts in the document
    - end_char: Character position where chunk ends in the document
    - section_title: Title of the parent section
    - section_level: Level of the parent section (level_1/2/3)

    Args:
        chunks: List of chunk dictionaries from MarkdownChunker
        parent_sections: Dict mapping doc_ids to section data with start_char/end_char
        markdown_content: Original markdown content

    Returns:
        List of chunk dictionaries with citation metadata added
    """
    logger.info(f"Adding citation metadata to {len(chunks)} chunks")

    for chunk_data in chunks:
        metadata = chunk_data["metadata"]
        chunk_content = chunk_data["content"]

        # Find the chunk's position in the original markdown content
        # Use the first 150 characters of chunk content for matching (more reliable)
        search_text = chunk_content[:150].strip()

        try:
            chunk_start_pos = find_chunk_in_markdown(search_text, markdown_content)

            if chunk_start_pos == -1:
                # Try without header if chunk has one
                if "\n\n" in chunk_content:
                    parts = chunk_content.split("\n\n", 1)
                    if len(parts) > 1:
                        search_text = parts[1][:150].strip()
                        chunk_start_pos = find_chunk_in_markdown(
                            search_text, markdown_content
                        )

            if chunk_start_pos == -1 and metadata.get("node_type") == "table":
                # Table chunks are HTML-transformed (Field: X, Desc: Y format).
                # Try every colon-separated segment as a potential cell value.
                for line in chunk_content.split("\n"):
                    # Split on ", " then extract value after ": " in each segment
                    for segment in line.split(", "):
                        if ": " in segment:
                            value_part = segment.split(": ", 1)[-1].strip().rstrip(".")
                            if len(value_part) > 10:
                                chunk_start_pos = find_chunk_in_markdown(
                                    value_part[:150], markdown_content
                                )
                                if chunk_start_pos != -1:
                                    break
                    if chunk_start_pos != -1:
                        break

            if chunk_start_pos != -1:
                chunk_end_pos = chunk_start_pos + len(chunk_content)

                # Find which parent section contains this chunk
                best_match = None
                best_match_doc_id = None

                for doc_id, section_data in parent_sections.items():
                    section_start = section_data.get("start_char", 0)
                    section_end = section_data.get("end_char", len(markdown_content))

                    # Check if chunk is within this section
                    if section_start <= chunk_start_pos < section_end:
                        # Prefer more specific matches (level_1 > level_2 > level_3)
                        level_priority = {"level_1": 3, "level_2": 2, "level_3": 1}
                        current_priority = level_priority.get(section_data["level"], 0)

                        if best_match is None or current_priority > level_priority.get(
                            best_match["level"], 0
                        ):
                            best_match = section_data
                            best_match_doc_id = doc_id

                if best_match and best_match_doc_id:
                    # Store citation metadata (library_card_id will be resolved during linking)
                    metadata["citation"] = {
                        "library_card_doc_id": best_match_doc_id,  # Hash to be resolved to ID later
                        "start_char": chunk_start_pos,
                        "end_char": chunk_end_pos,
                        "section_title": best_match["title"],
                        "section_level": best_match["level"],
                    }
                    logger.debug(
                        f"Chunk {metadata['chunk_index']}: Citation added (section='{best_match['title']}', pos={chunk_start_pos}-{chunk_end_pos})"
                    )
                else:
                    logger.warning(
                        f"Chunk {metadata['chunk_index']}: No matching parent section found"
                    )
                    metadata["citation"] = None
            else:
                logger.warning(
                    f"Chunk {metadata['chunk_index']}: Could not find chunk position in document"
                )
                metadata["citation"] = None

        except Exception as e:
            logger.error(
                f"Error adding citation to chunk {metadata.get('chunk_index', '?')}: {e}"
            )
            metadata["citation"] = None

    logger.info("Citation metadata added to all chunks")
    return chunks


