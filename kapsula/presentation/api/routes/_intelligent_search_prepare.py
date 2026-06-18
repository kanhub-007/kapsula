"""Shared intelligent search preparation logic.

Thin adapter: delegates to ``PrepareIntelligentSearchUseCase`` (closes A6).
Kept as a module function so the route handlers can stay synchronous-ish
and so the streaming route can reuse the same preparation path.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


async def _prepare_intelligent_search(
    query: str,
    account_id: str | None,
    enable_planning: bool,
    db: Session,
):
    """Prepare a search via the shared use case.

    Returns (search_plan, collections, routed_collection) tuple for
    backward compatibility with existing route handlers, or raises
    HTTPException(404) when no collections are available.
    """
    from kapsula.startup import create_prepare_intelligent_search_use_case

    use_case = create_prepare_intelligent_search_use_case(db)
    try:
        preparation = use_case.prepare(query, account_id, enable_planning)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return (
        preparation.plan,
        preparation.collections,
        preparation.routed_collection,
    )
