from __future__ import annotations

from typing_extensions import TypedDict


class PrimaState(TypedDict, total=False):
    """Shared state threaded through the agent graph. ``total=False`` so each node
    contributes only the keys it produces (LangGraph merges them in)."""

    question: str
    focus: dict           # orchestrator: parsed intent / entities
    sql: str              # sql_analyst: the read-only query it authored
    rows: list[dict]      # sql_analyst: BigQuery result
    feature_cols: list[str]
    detection: dict       # detector: counts, flagged windows, optional graded F1
    root_cause: dict      # root_cause: ranked deviating features
    briefing: str         # narrator: final reliability briefing
    error: str | None
