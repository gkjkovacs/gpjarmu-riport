"""
Graph node: dedupe

Drops items that have already been reported (state DB).
Returns a list of "new" items that the orchestrator should persist and expand.
"""

from __future__ import annotations

import logging

from ...config import Settings
from ...scraper.magyarkozlony import content_hash
from ...state.db import StateDB

logger = logging.getLogger(__name__)


def dedupe(state: dict, settings: Settings, db: StateDB) -> dict:
    """Drop already-reported items. Return new_items list."""
    relevant: list[dict] = state.get("relevant", [])
    if not relevant:
        logger.info("No relevant items to dedupe")
        return {"new_items": []}

    logger.info("Deduplicating %d relevant items against state DB…", len(relevant))
    new_items: list[dict] = []
    dropped = 0

    for r in relevant:
        issue_number = r["issue_number"]
        anchor = r["anchor"]
        if db.is_already_reported(issue_number, anchor):
            dropped += 1
            continue

        # Build a synthetic Bekezdes for content_hash
        from ...scraper.magyarkozlony import Bekezdes
        b = Bekezdes(anchor=anchor, heading="", text=r["text"])
        h = content_hash(b)

        new_items.append({
            "issue_number": issue_number,
            "issue_id": r["issue_id"],
            "issue_date": r["issue_date"],
            "anchor": anchor,
            "text": r["text"],
            "indokolas_url": r.get("indokolas_url"),
            "score": float(r.get("score", 0.0)),
            "matched_topics": r.get("matched_topics", []),
            "one_line_summary_hu": r.get("one_line_summary_hu", ""),
            "reasoning_hu": r.get("reasoning_hu", ""),
            "content_hash": h,
        })

    logger.info("New items: %d (dropped: %d already reported)", len(new_items), dropped)
    return {"new_items": new_items}


__all__ = ["dedupe"]
