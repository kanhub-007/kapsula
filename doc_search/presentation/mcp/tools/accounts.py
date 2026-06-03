"""Account management MCP tools."""

import uuid

from fastmcp import FastMCP

from doc_search.infrastructure.data import Account
from ._shared import _get_db, _resolve_account


def register_account_tools(mcp: FastMCP):
    @mcp.tool(
        name="create_account",
        description="Create a new account — the top-level memory container (think: a brain or tenant). An account holds collections (knowledge domains), which hold documents (topics). Returns the account GUID.",
    )
    def create_account(name: str) -> str:
        db = _get_db()
        try:
            account_id = str(uuid.uuid4())
            acc = Account(account_id=account_id, name=name, ip_address="127.0.0.1")
            db.add(acc)
            db.commit()
            return f"Account created: {name}\n  account_id: {account_id}"
        finally:
            db.close()

    @mcp.tool(
        name="list_accounts",
        description="List all accounts with collection counts.",
    )
    def list_accounts() -> str:
        db = _get_db()
        try:
            accounts = db.query(Account).order_by(Account.created_at.desc()).all()
            if not accounts:
                return "No accounts found."
            lines = [f"Accounts ({len(accounts)}):\n"]
            for a in accounts:
                lines.append(
                    f"  • {a.name} — {len(a.collections)} collections — {a.account_id}"
                )
            return "\n".join(lines)
        finally:
            db.close()

    @mcp.tool(
        name="get_account",
        description="Get account details including all collections and document counts.",
    )
    def get_account(account_id: str) -> str:
        db = _get_db()
        try:
            acc = _resolve_account(db, account_id)
            if not acc:
                return f"Account not found: {account_id}"
            lines = [
                f"Account: {acc.name}",
                f"account_id: {acc.account_id}",
                f"Created: {acc.created_at.isoformat() if acc.created_at else '?'}",
                f"Collections: {len(acc.collections)}",
            ]
            for col in acc.collections:
                lines.append(
                    f"  • {col.name} ({len(col.documents)} docs) — {col.collection_id}"
                )
            return "\n".join(lines)
        finally:
            db.close()
