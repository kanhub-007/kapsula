"""SubDocumentPage domain entity."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class SubDocumentPage:
    id: int | None = None
    sub_document_id: int | None = None
    page_title: str = ""
    breadcrumb_full: str = ""
    content_hash: str | None = None
    created_at: datetime | None = None
