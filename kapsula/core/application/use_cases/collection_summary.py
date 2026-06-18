"""LLM-based collection library card summary generation."""

import logging
from typing import Any

from kapsula.core.domain.interfaces.chat_client import ChatClient

logger = logging.getLogger(__name__)


class CollectionSummaryGenerator:
    """Generates LLM summaries for collection library cards."""

    def __init__(self, chat_client: ChatClient):
        self._chat_client = chat_client
        logger.info("CollectionSummaryGenerator initialized")

    def generate_new_collection_summary(
        self,
        collection_name: str,
        document_summary: str,
        document_filename: str,
        document_metadata: dict[str, Any],
    ) -> str:
        subdoc_info = ""
        if "sub_documents" in document_metadata:
            subdocs = document_metadata["sub_documents"]
            names = list(subdocs.keys())[:3]
            subdoc_info = (
                f"\nSubdocuments ({len(subdocs)}): {', '.join(names)}"
                f"{'...' if len(subdocs) > 3 else ''}"
            )

        user_message = (
            f"Create a concise summary (2-3 sentences) for this document collection.\n"
            f"Focus on: main topics covered, document types, and key themes.\n\n"
            f"Collection Name: {collection_name}\n"
            f"Document: {document_filename}\n"
            f"Document Summary: {document_summary}{subdoc_info}\n\n"
            f"Provide only the summary, no additional text:"
        )

        try:
            summary = self._chat_client.send(
                messages=[{"role": "user", "content": user_message}],
                max_tokens=150,
                temperature=0.3,
            ).strip()
            logger.debug(f"Generated new collection summary: {summary[:100]}...")
            return summary
        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            return f"Collection containing {document_filename}"

    def generate_incremental_summary(
        self,
        collection_name: str,
        existing_summary: str,
        existing_documents: list,
        new_document_summary: str,
        new_document_filename: str,
        new_document_metadata: dict[str, Any],
    ) -> str:
        existing_text = "\n".join(
            f"- {d['filename']}: {d['summary'][:100]}..."
            for d in existing_documents[:5]
        )
        if len(existing_documents) > 5:
            existing_text += f"\n... and {len(existing_documents) - 5} more documents"

        subdoc_info = ""
        if "sub_documents" in new_document_metadata:
            subdocs = new_document_metadata["sub_documents"]
            names = list(subdocs.keys())[:3]
            subdoc_info = (
                f"\nSubdocuments ({len(subdocs)}): {', '.join(names)}"
                f"{'...' if len(subdocs) > 3 else ''}"
            )

        user_message = (
            f"Update the collection summary by incorporating a newly added document.\n"
            f"Preserve existing themes and add new ones if relevant. Keep it concise (2-3 sentences).\n\n"
            f"Collection Name: {collection_name}\n\n"
            f"Existing Collection Summary:\n{existing_summary}\n\n"
            f"Existing Documents ({len(existing_documents)}):\n{existing_text}\n\n"
            f"New Document Added:\n"
            f"Filename: {new_document_filename}\n"
            f"Summary: {new_document_summary}{subdoc_info}\n\n"
            f"Provide only the updated summary, no additional text:"
        )

        try:
            summary = self._chat_client.send(
                messages=[{"role": "user", "content": user_message}],
                max_tokens=150,
                temperature=0.3,
            ).strip()
            logger.debug(f"Generated updated collection summary: {summary[:100]}...")
            return summary
        except Exception as e:
            logger.error(f"Incremental summary generation failed: {e}")
            return f"{existing_summary} Includes {new_document_filename}."
