"""
Graph node: discover_issues

Lists Magyar Közlöny issues published within [lookback_start, lookback_end].
Skips issues already fully processed (state DB).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from ...config import Settings
from ...scraper.magyarkozlony import MagyarKozlonyClient
from ...state.db import StateDB

logger = logging.getLogger(__name__)


def discover_issues(state: dict, settings: Settings, db: StateDB) -> dict:
    """List issues in the window. Returns a partial state update."""
    run_date = date.fromisoformat(state["run_date"])
    lookback_start = date.fromisoformat(state["lookback_start"])
    lookback_end = date.fromisoformat(state["lookback_end"])

    logger.info(
        "Discovering Magyar Közlöny issues in [%s, %s]…",
        lookback_start, lookback_end,
    )

    client = MagyarKozlonyClient(settings)
    try:
        issues = client.list_issues(lookback_start, lookback_end)
    except Exception as e:
        logger.exception("Issue discovery failed")
        return {
            "issues": [],
            "issues_scanned": 0,
            "errors": [f"Issue discovery failed: {e}"],
        }

    # Cap
    if len(issues) > settings.max_issues_per_run:
        logger.warning(
            "Capping issue list: %d → %d (MAX_ISSUES_PER_RUN)",
            len(issues), settings.max_issues_per_run,
        )
        issues = issues[: settings.max_issues_per_run]

    # Drop already-processed (optimization — the dedupe node still catches bekezdések)
    unprocessed = [i for i in issues if not db.is_issue_processed(i.issue_id)]
    skipped = len(issues) - len(unprocessed)

    if skipped:
        logger.info("Skipping %d already-processed issues", skipped)

    logger.info("Found %d issues (%d unprocessed)", len(issues), len(unprocessed))

    return {
        "issues": [
            {
                "number": i.number,
                "issue_id": i.issue_id,
                "date": i.date,
                "has_indokolas": i.has_indokolas,
                "megtekintes_url": i.megtekintes_url,
                "letoltes_url": i.letoltes_url,
                "indokolas_url": i.indokolas_url,
            }
            for i in unprocessed
        ],
        "issues_scanned": len(issues),
    }


__all__ = ["discover_issues"]
