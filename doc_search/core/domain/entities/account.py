"""Account domain entity."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Account:
    id: int | None = None
    account_id: str = ""
    name: str = ""
    created_at: datetime | None = None
