"""
Graph node: expand

For every new item, the LLM expands the one-line summary into a 2–4 sentence
paragraph, extracts key dates, and suggests action items.

Includes the same repair pass as the classify node: if the LLM produces
malformed JSON, we re-ask it once to fix the JSON before falling back to
the one-line summary. The expander output schema is *different* from the
classifier (expansion_hu, key_dates_hu, action_items_hu, links) so we
keep the parsing helpers local rather than sharing.
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


_STRICT_SUFFIX = (
    "\n\nFONTOS: A válaszod CSAK egyetlen JSON objektum legyen, "
    "semmilyen más szöveg, magyarázat, vagy markdown keret (```) nélkül. "
    "A JSON kulcsok: expansion_hu, key_dates_hu, action_items_hu, links. "
    "String értékekben ne legyen literál sortörés vagy escape-eletlen ASCII "
    'idézőjel (").'
)


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


def _safe_parse_json(text: str) -> dict[str, Any] | None:
    """Try to extract a JSON object from the LLM response. Returns None on failure."""
    try:
        return _extract_json(text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.debug("Expander JSON parse failed: %s — raw: %r", e, text[:200])
        return None


def _coerce_expander_result(parsed: dict[str, Any], fallback_one_line: str) -> dict[str, Any]:
    """Normalize a parsed expander dict to our internal schema. Always returns a dict."""
    parsed.setdefault("expansion_hu", fallback_one_line)
    parsed.setdefault("key_dates_hu", [])
    parsed.setdefault("action_items_hu", [])
    if not isinstance(parsed["key_dates_hu"], list):
        parsed["key_dates_hu"] = []
    if not isinstance(parsed["action_items_hu"], list):
        parsed["action_items_hu"] = []
    return parsed


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
    """Expand one item. Returns a dict with expansion_hu, key_dates_hu, action_items_hu.

    On JSON parse failure, retries once with a "fix your JSON" repair prompt.
    If the repair also fails, falls back to the one-line summary so the item
    is still included in the report.
    """
    fallback = item.get("one_line_summary_hu", "")
    user_msg = _build_user_message(item)
    try:
        response = await llm.ainvoke([
            SystemMessage(content=REPORT_WRITER_SYSTEM),
            HumanMessage(content=user_msg),
        ])
    except Exception as e:
        logger.warning("Expander LLM call failed: %s", e)
        return {
            "expansion_hu": fallback,
            "key_dates_hu": [],
            "action_items_hu": [],
            "error": f"llm_call_failed: {e}",
        }
    raw = response.content if isinstance(response.content, str) else str(response.content)
    parsed = _safe_parse_json(raw)
    if parsed is not None:
        return _coerce_expander_result(parsed, fallback)

    # --- Repair pass ---
    logger.warning(
        "Expander returned invalid JSON (first attempt) — requesting repair. raw[:200]=%r",
        raw[:200],
    )
    repair_prompt = (
        "Your previous response was not valid JSON. Here is the raw output:\n\n"
        "<<<" + raw + ">>>\n\n"
        "Please re-emit the SAME answer as a single valid JSON object with the exact same "
        "keys (expansion_hu, key_dates_hu, action_items_hu, and optionally links). "
        "Remember: no literal newlines inside any string, and no unescaped ASCII double-quote "
        'characters (") inside string values. Output the JSON object only — no prose, no '
        "markdown fences."
    )
    try:
        response2 = await llm.ainvoke([
            SystemMessage(content=REPORT_WRITER_SYSTEM),
            HumanMessage(content=repair_prompt),
        ])
    except Exception as e:
        logger.warning("Expander repair LLM call failed: %s", e)
        return {
            "expansion_hu": fallback,
            "key_dates_hu": [],
            "action_items_hu": [],
            "error": f"parse_failed: {type(e).__name__}: {e}",
        }
    raw2 = response2.content if isinstance(response2.content, str) else str(response2.content)
    parsed2 = _safe_parse_json(raw2)
    if parsed2 is not None:
        logger.info("Expander repair pass succeeded for anchor=%r", item.get("anchor"))
        return _coerce_expander_result(parsed2, fallback)

    logger.warning(
        "Expander JSON still unparseable after repair. raw[:200]=%r",
        raw2[:200],
    )
    # Fall back gracefully: include the one-line summary so the user still sees
    # this item in the report. The error flag marks it for the log.
    return {
        "expansion_hu": fallback,
        "key_dates_hu": [],
        "action_items_hu": [],
        "error": "parse_failed_after_repair",
    }


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
