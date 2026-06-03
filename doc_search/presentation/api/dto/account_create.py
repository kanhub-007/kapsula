"""Account create API DTO."""

from pydantic import BaseModel


class AccountCreate(BaseModel):
    """Request model for creating an account."""

    name: str
