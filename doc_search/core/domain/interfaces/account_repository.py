"""Repository interface for Account persistence."""

from abc import ABC, abstractmethod

from doc_search.core.domain.entities.account import Account


class AccountRepository(ABC):
    """Persistence for accounts."""

    @abstractmethod
    def list_all(self, db) -> list[Account]:
        """Return all accounts ordered by creation date descending."""

    @abstractmethod
    def find_by_account_id(self, db, account_id: str) -> Account | None:
        """Return the account with the given GUID, or None."""

    @abstractmethod
    def save(self, db, account: Account) -> None:
        """Persist a new account and flush its identity."""
