"""Repository interface for Account persistence."""

from abc import ABC, abstractmethod
from typing import Any

from kapsula.core.domain.entities.account import Account


class AccountRepository(ABC):
    """Persistence for accounts."""

    @abstractmethod
    def list_all(self, db: Any) -> list[Account]:
        """Return all accounts ordered by creation date descending."""

    @abstractmethod
    def find_by_account_id(self, db: Any, account_id: str) -> Account | None:
        """Return the account with the given GUID, or None."""

    @abstractmethod
    def save(self, db: Any, account: Account) -> Account:
        """Persist a new account and return it with the generated identity."""
