"""
Graph node: fetch_content

Fetches each issue's bekezdések (paragraphs) and indokolás (if present).
Returns a mapping: issue_id -> list of bekezdések.
"""

from __future__ import annotations

import logging

from ...config import Settings
from ...scraper.magyarkozlony import MagyarKozlonyClient, Bekezdes, IssueMeta

logger = logging.getLogger(__name__)


def _meta_from_dict(d: dict) -> IssueMeta:
    return IssueMeta(
        number=d["number"],
        issue_id=d["issue_id"],
        date=d["date"],
        has_indokolas=d["has_indokolas"],
        megtekintes_url=d["megtekintes_url"],
        letoltes_url=d["letoltes_url"],
        indokolas_url=d.get("indokolas_url"),
    )


def fetch_content(state: dict, settings: Settings) -> dict:
    """Fetch and parse bekezdések for every issue in state['issues']."""
    issues: list[dict] = state.get("issues", [])
    if not issues:
        logger.info("No issues to fetch — skipping fetch_content node")
        return {"bekezdes_by_issue": {}}

    logger.info("Fetching content for %d issues…", len(issues))
    client = MagyarKozlonyClient(settings)
    bekezdes_by_issue: dict[str, list[dict]] = {}
    warnings: list[str] = list(state.get("warnings", []))

    for issue_dict in issues:
        issue_id = issue_dict["issue_id"]
        try:
            meta = _meta_from_dict(issue_dict)
            bekezdes_list: list[Bekezdes] = client.fetch_issue_content(meta)
        except Exception as e:
            msg = f"fetch_content failed for {issue_id}: {e}"
            logger.warning(msg)
            warnings.append(msg)
            continue

        # Filter by length
        min_len = settings.min_bekezdes_length
        bekezdes_list = [b for b in bekezdes_list if len(b.text) >= min_len]

        bekezdes_by_issue[issue_id] = [
            {
                "anchor": b.anchor,
                "heading": b.heading,
                "text": b.text,
                "has_indokolas": b.has_indokolas,
                "indokolas_url": b.indokolas_url,
                "indokolas_text": b.indokolas_text,
            }
            for b in bekezdes_list
        ]
        logger.info(
            "  %s: %d bekezdés (≥%d chars)",
            issue_id, len(bekezdes_list), min_len,
        )

    return {"bekezdes_by_issue": bekezdes_by_issue, "warnings": warnings}


__all__ = ["fetch_content"]
