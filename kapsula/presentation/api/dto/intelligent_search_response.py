from __future__ import annotations

from pydantic import BaseModel

from kapsula.presentation.api.dto.citation import Citation
from kapsula.presentation.api.dto.search_plan import SearchPlan
from kapsula.presentation.api.dto.sub_answer import SubAnswer


class IntelligentSearchResponse(BaseModel):
    """Response model for intelligent search on document."""

    job_id: str
    query: str
    answer: str
    has_answer: bool
    relevant_results: list[int]
    total_evaluated: int
    context_mode: str | None = None
    plan: SearchPlan | None = None
    sub_answers: list[SubAnswer] | None = None
    citations: list[Citation] | None = None  # All unique citations from search results
