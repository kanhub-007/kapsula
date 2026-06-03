"""Account domain entity — canonical model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Account:
    """A tenant / top-level container for collections."""

    id: int | None = None
    account_id: str = ""
    name: str = ""
    created_at: datetime | None = None
    ip_address: str = ""

    # Navigation
    collections: list[Collection] = field(default_factory=list)
