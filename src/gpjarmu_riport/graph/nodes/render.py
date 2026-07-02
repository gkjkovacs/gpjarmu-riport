"""
Graph node: render_email

Assembles the final .txt report and persists the new items to the state DB
so they don't get reported again.

History: this used to produce a multipart/alternative .eml file and
(optionally) send it via SMTP. We now produce a simple UTF-8 .txt file —
the user reads it directly, or the Windows Task Scheduler can attach it
to an email later. The SMTP transport is kept in the email package for
future re-enablement but is no longer called from the pipeline.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from pathlib import Path

from ...config import Settings
from ...email import render_and_save_report
from ...state.db import ReportedItem, StateDB

logger = logging.getLogger(__name__)


def render_email(state: dict, settings: Settings, db: StateDB) -> dict:
    """Build the .txt report, save it, and persist state."""
    run_date = state["run_date"]
    lookback_start = state["lookback_start"]
    lookback_end = state["lookback_end"]
    expanded_items: list[dict] = state.get("expanded_items", [])
    new_items_count = len(expanded_items)

    # Group by issue for the report body
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for item in expanded_items:
        key = (item["issue_number"], item["issue_date"])
        grouped[key].append(item)

    # Sort by date desc, then by issue number, then by anchor
    sorted_issues = sorted(
        grouped.items(),
        key=lambda kv: (kv[0][1], kv[0][0]),
        reverse=True,
    )
    grouped_issues = [
        {
            "number": number,
            "date": date_,
            "items": sorted(items, key=lambda i: i["anchor"]),
        }
        for (number, date_), items in sorted_issues
    ]

    report_path: Path | None = None

    if not settings.dry_run:
        report_path = render_and_save_report(
            output_dir=settings.output_dir,
            run_date=run_date,
            lookback_start=lookback_start,
            lookback_end=lookback_end,
            issues_scanned=state.get("issues_scanned", 0),
            new_items_count=new_items_count,
            grouped_issues=grouped_issues,
            settings=settings,
        )
    else:
        logger.info("DRY_RUN=true — skipping .txt report write")

    # Persist state
    persisted = 0
    for item in expanded_items:
        if settings.dry_run:
            continue
        reported = ReportedItem(
            issue_number=item["issue_number"],
            anchor=item["anchor"],
            issue_date=item["issue_date"],
            content_hash=item.get("content_hash", ""),
            score=item["score"],
            matched_topics=item.get("matched_topics", []),
            one_line_summary_hu=item.get("one_line_summary_hu", ""),
            expansion_hu=item.get("expansion_hu", ""),
            key_dates_hu=item.get("key_dates_hu", []),
            action_items_hu=item.get("action_items_hu", []),
            indokolas_url=item.get("indokolas_url"),
        )
        if db.mark_reported(reported):
            persisted += 1

    # Mark issues as processed
    processed_issue_ids = {it["issue_id"] for it in expanded_items}
    for issue_dict in state.get("issues", []):
        if issue_dict["issue_id"] not in processed_issue_ids:
            # No relevant items from this issue, but mark as fully processed
            db.mark_issue_processed(
                issue_number=issue_dict["issue_id"],
                issue_date=issue_dict["date"],
                items_classified=sum(
                    len(v) for k, v in state.get("bekezdes_by_issue", {}).items()
                    if k == issue_dict["issue_id"]
                ),
                items_relevant=0,
            )
    for issue_dict in state.get("issues", []):
        if issue_dict["issue_id"] in processed_issue_ids:
            items_relevant_for_issue = sum(
                1 for it in expanded_items if it["issue_id"] == issue_dict["issue_id"]
            )
            items_classified_for_issue = len(
                state.get("bekezdes_by_issue", {}).get(issue_dict["issue_id"], [])
            )
            db.mark_issue_processed(
                issue_number=issue_dict["issue_id"],
                issue_date=issue_dict["date"],
                items_classified=items_classified_for_issue,
                items_relevant=items_relevant_for_issue,
            )

    # Update run_meta
    if not settings.dry_run:
        db.set_last_run_date(date.fromisoformat(run_date))
        db.bump_total_reported(persisted)

    logger.info(
        "Run complete. New items: %d / persisted: %d / report: %s",
        new_items_count, persisted,
        str(report_path) if report_path else "(dry run)",
    )

    return {
        "report_path": str(report_path) if report_path else "",
        "eml_sent": False,  # SMTP path no longer wired up
        "new_items_count": new_items_count,
    }


__all__ = ["render_email"]
