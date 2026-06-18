"""Collection domain entity — canonical model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kapsula.core.domain.entities.account import Account
    from kapsula.core.domain.entities.document import Document


@dataclass
class Collection:
    """A knowledge domain grouping related documents."""

    id: int | None = None
    collection_id: str = ""
    account_id: int | None = None
    name: str = ""
    logo_filename: str | None = None
    created_at: datetime | None = None
    ip_address: str = ""

    account: Account | None = None
    documents: list[Document] = field(default_factory=list)
