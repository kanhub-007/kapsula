"""Account list response API DTO."""

from pydantic import BaseModel

from kapsula.presentation.api.dto.account_response import AccountResponse


class AccountListResponse(BaseModel):
    """Response model for account list."""

    accounts: list[AccountResponse]
    total: int
