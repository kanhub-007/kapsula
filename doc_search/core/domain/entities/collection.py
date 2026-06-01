"""Collection domain entity."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Collection:
    id: int | None = None
    collection_id: str = ""
    account_id: int | None = None
    name: str = ""
    logo_filename: str | None = None
    created_at: datetime | None = None
