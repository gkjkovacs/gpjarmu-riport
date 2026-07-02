"""
Graph node: expand

For every new item, the LLM expands the one-line summary into a 2–4 sentence
paragraph, extracts key dates, and suggests action items.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ...config import Settings
from ...llm_factory import get_expander
from ...prompts import REPORT_WRITER_SYSTEM

logger = logging.getLogger(__name__)


_STRICT_SUFFIX = "\nVálaszolj kizárólag érvényes JSON-nel, semmilyen más szöveget ne írj."


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in expander response.")
    return json.loads(m.group(0))


def _build_user_message(item: dict) -> str:
    lines = [
        f"Bekezdés anchor: {item['anchor']}",
        f"Relevancia score: {item['score']:.2f}",
        f"Témák: {', '.join(item.get('matched_topics', [])) or '(nincs)'}",
        f"Egysoros összefoglaló: {item['one_line_summary_hu']}",
        "",
        "Bekezdés szövege:",
        "<<<",
        item["text"].strip(),
        ">>>",
    ]
    if item.get("indokolas_text", "").strip():
        lines += ["", "Indokolás:", "<<<", item["indokolas_text"].strip(), ">>>"]
    if item.get("indokolas_url"):
        lines += ["", f"Indokolas URL: {item['indokolas_url']}"]
    lines.append(_STRICT_SUFFIX)
    return "\n".join(lines)


async def _expand_one(llm, item: dict) -> dict[str, Any]:
    user_msg = _build_user_message(item)
    try:
        response = await llm.ainvoke([
            SystemMessage(content=REPORT_WRITER_SYSTEM),
            HumanMessage(content=user_msg),
        ])
    except Exception as e:
        logger.warning("Expander LLM call failed: %s", e)
        return {
            "expansion_hu": item.get("one_line_summary_hu", ""),
            "key_dates_hu": [],
            "action_items_hu": [],
            "error": f"llm_call_failed: {e}",
        }
    raw = response.content if isinstance(response.content, str) else str(response.content)
    try:
        parsed = _extract_json(raw)
    except Exception as e:
        logger.warning("Expander JSON parse failed: %s", e)
        return {
            "expansion_hu": item.get("one_line_summary_hu", ""),
            "key_dates_hu": [],
            "action_items_hu": [],
            "error": f"parse_failed: {e}",
        }
    parsed.setdefault("expansion_hu", item.get("one_line_summary_hu", ""))
    parsed.setdefault("key_dates_hu", [])
    parsed.setdefault("action_items_hu", [])
    if not isinstance(parsed["key_dates_hu"], list):
        parsed["key_dates_hu"] = []
    if not isinstance(parsed["action_items_hu"], list):
        parsed["action_items_hu"] = []
    return parsed


async def expand(state: dict, settings: Settings) -> dict:
    """Expand each new item via the LLM. Returns expanded_items."""
    new_items: list[dict] = state.get("new_items", [])
    if not new_items:
        logger.info("No new items to expand")
        return {"expanded_items": []}

    logger.info("Expanding %d new items via LLM…", len(new_items))
    llm = get_expander()
    expanded: list[dict] = []
    errors = 0

    for item in new_items:
        result = await _expand_one(llm, item)
        if result.get("error"):
            errors += 1
        expanded.append({
            "issue_number": item["issue_number"],
            "issue_id": item["issue_id"],
            "issue_date": item["issue_date"],
            "anchor": item["anchor"],
            "score": item["score"],
            "matched_topics": item.get("matched_topics", []),
            "one_line_summary_hu": item.get("one_line_summary_hu", ""),
            "expansion_hu": result.get("expansion_hu", item.get("one_line_summary_hu", "")),
            "key_dates_hu": result.get("key_dates_hu", []),
            "action_items_hu": result.get("action_items_hu", []),
            "indokolas_url": item.get("indokolas_url"),
            "content_hash": item.get("content_hash", ""),
        })

    logger.info("Expanded %d / errors %d", len(expanded), errors)
    return {"expanded_items": expanded}


__all__ = ["expand"]
