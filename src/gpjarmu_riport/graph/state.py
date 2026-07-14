"""
LangGraph state schema for the Magyar Közlöny monitor pipeline.

The state flows through 6 nodes:
  1. discover_issues   — list issues in the lookback window
  2. fetch_content     — fetch + parse each issue's bekezdések
  3. classify          — LLM relevance classification
  4. dedupe            — drop items already reported (state DB)
  5. expand            — LLM summary expansion
  6. render_email      — produce the .txt report
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class BekezdesItem(TypedDict):
    """A classified (and possibly expanded) bekezdés ready for the report body."""

    issue_number: str
    issue_date: str
    anchor: str
    score: float
    matched_topics: list[str]
    one_line_summary_hu: str
    expansion_hu: str
    key_dates_hu: list[str]
    action_items_hu: list[str]
    indokolas_url: Optional[str]
    content_hash: str


class GraphState(TypedDict, total=False):
    """The full state passed between LangGraph nodes."""

    # --- Run metadata ---
    run_date: str                       # ISO date — set by runner, used everywhere
    lookback_start: str                 # ISO date
    lookback_end: str                   # ISO date (= run_date)

    # --- Discover node output ---
    issues: list[dict[str, Any]]        # list[IssueMeta] serialized as dicts

    # --- Fetch node output ---
    bekezdes_by_issue: dict[str, list[dict[str, Any]]]
    # map: issue_id -> list of {anchor, heading, text, indokolas_url, indokolas_text}

    # --- Classify node output ---
    classified: list[dict[str, Any]]    # full classification per bekezdés
    relevant: list[dict[str, Any]]      # filtered: score >= threshold

    # --- Dedupe node output ---
    new_items: list[dict[str, Any]]     # not yet reported (will be persisted)

    # --- Expand node output ---
    expanded_items: list[BekezdesItem]  # ready for the report

    # --- Render node output ---
    report_path: str                    # path to the saved .txt report
    email_sent: bool                    # True if SMTP send succeeded
    new_items_count: int                # convenience counter

    # --- Diagnostics ---
    warnings: list[str]                 # human-readable warnings
    errors: list[str]                   # fatal errors
    issues_scanned: int                 # how many issues were touched

    # --- LLM message log (for debugging) ---
    messages: Annotated[list[BaseMessage], add_messages]


__all__ = ["GraphState", "BekezdesItem"]
