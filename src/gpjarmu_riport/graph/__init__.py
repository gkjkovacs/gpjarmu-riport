"""
LangGraph StateGraph assembly.

The graph is a 6-node linear pipeline:

    START
      → discover_issues
        → fetch_content
          → classify     (LLM call)
            → dedupe     (state DB lookup)
              → expand   (LLM call)
                → render_email
                  → END
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph

from ..config import Settings
from ..state.db import StateDB
from .nodes import (
    classify,
    dedupe,
    discover_issues,
    expand,
    fetch_content,
    render_email,
)
from .state import GraphState

logger = logging.getLogger(__name__)


def _initial_state(settings: Settings) -> dict[str, Any]:
    """Build the initial state for a run."""
    run_date = date.today()
    last_run = None  # filled by the runner
    return {
        "run_date": run_date.isoformat(),
        "lookback_start": (run_date - timedelta(days=settings.lookback_days)).isoformat(),
        "lookback_end": run_date.isoformat(),
        "issues": [],
        "bekezdes_by_issue": {},
        "classified": [],
        "relevant": [],
        "new_items": [],
        "expanded_items": [],
        "issues_scanned": 0,
        "warnings": [],
        "errors": [],
    }


def build_graph(settings: Settings, db: StateDB) -> Any:
    """
    Build and compile the StateGraph.

    The runner can then call `graph.invoke(initial_state)`.
    """
    workflow = StateGraph(GraphState)

    # Bind settings + db to each node
    workflow.add_node("discover_issues", partial(discover_issues, settings=settings, db=db))
    workflow.add_node("fetch_content", partial(fetch_content, settings=settings))
    workflow.add_node("classify", partial(classify, settings=settings))
    workflow.add_node("dedupe", partial(dedupe, settings=settings, db=db))
    workflow.add_node("expand", partial(expand, settings=settings))
    workflow.add_node("render_email", partial(render_email, settings=settings, db=db))

    workflow.add_edge(START, "discover_issues")
    workflow.add_edge("discover_issues", "fetch_content")
    workflow.add_edge("fetch_content", "classify")
    workflow.add_edge("classify", "dedupe")
    workflow.add_edge("dedupe", "expand")
    workflow.add_edge("expand", "render_email")
    workflow.add_edge("render_email", END)

    return workflow.compile()


async def run_pipeline(
    settings: Settings,
    db: StateDB,
    seed: bool = False,
) -> dict[str, Any]:
    """
    Run the full pipeline. Returns the final graph state.

    If `seed=True`, the lookback window starts at `today - lookback_days`
    regardless of `last_run`. Used for the initial 30-day seed.
    """
    graph = build_graph(settings, db)
    state = _initial_state(settings)

    if not seed:
        last_run = db.get_last_run_date()
        if last_run is not None:
            # Look back from the later of (last_run, today - lookback_days)
            earliest = date.today() - timedelta(days=settings.lookback_days)
            state["lookback_start"] = str(max(last_run, earliest))

    logger.info("Starting pipeline (seed=%s)…", seed)
    result = await graph.ainvoke(state)
    logger.info("Pipeline complete. new_items_count=%d", result.get("new_items_count", 0))
    return result


__all__ = ["build_graph", "run_pipeline"]
