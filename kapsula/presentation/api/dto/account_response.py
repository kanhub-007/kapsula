"""Account response API DTO."""

from pydantic import BaseModel


class AccountResponse(BaseModel):
    """Response model for account."""

    account_id: str
    name: str
    created_at: str
    collection_count: int
