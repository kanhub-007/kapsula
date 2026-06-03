"""Account list response API DTO."""

from typing import List

from pydantic import BaseModel

from doc_search.presentation.api.dto.account_response import AccountResponse


class AccountListResponse(BaseModel):
    """Response model for account list."""

    accounts: List[AccountResponse]
    total: int
