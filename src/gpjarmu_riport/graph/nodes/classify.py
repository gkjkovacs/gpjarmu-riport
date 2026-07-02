"""
Graph node: classify

For every bekezdés across all fetched issues, ask the LLM to score
relevance (0.00–1.00) against the "Gépjármű / Céges Gépjármű" taxonomy.
Keep only bekezdések with score >= RELEVANCE_THRESHOLD.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ...config import Settings
from ...llm_factory import get_classifier
from ...prompts import RELEVANCE_CLASSIFIER_SYSTEM

logger = logging.getLogger(__name__)


_STRICT_SUFFIX = (
    "\n\nFONTOS: A válaszod CSAK egyetlen JSON objektum legyen, "
    "semmilyen más szöveg, magyarázat, vagy markdown keret (```) nélkül. "
    "A JSON kulcsok: is_relevant, score, matched_topics, "
    "one_line_summary_hu, reasoning_hu."
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
        raise ValueError("No JSON object found in classifier response.")
    return json.loads(m.group(0))


def _build_user_message(b: dict[str, Any]) -> str:
    parts = ["Bekezdés szövege:", "<<<", b["text"].strip(), ">>>"]
    if b.get("indokolas_text", "").strip():
        parts += ["", "Indokolás (kontextus):", "<<<", b["indokolas_text"].strip(), ">>>"]
    return "\n".join(parts) + _STRICT_SUFFIX


async def _classify_one(llm, b: dict[str, Any]) -> dict[str, Any]:
    """Classify a single bekezdés. Returns parsed JSON dict."""
    user_msg = _build_user_message(b)
    try:
        response = await llm.ainvoke([
            SystemMessage(content=RELEVANCE_CLASSIFIER_SYSTEM),
            HumanMessage(content=user_msg),
        ])
    except Exception as e:
        logger.warning("LLM call failed: %s", e)
        return {
            "is_relevant": False, "score": 0.0,
            "matched_topics": [], "one_line_summary_hu": "", "reasoning_hu": "",
            "error": f"llm_call_failed: {e}",
        }
    raw = response.content if isinstance(response.content, str) else str(response.content)
    try:
        parsed = _extract_json(raw)
    except Exception as e:
        logger.warning("JSON parse failed: %s — raw: %r", e, raw[:200])
        return {
            "is_relevant": False, "score": 0.0,
            "matched_topics": [], "one_line_summary_hu": "", "reasoning_hu": "",
            "error": f"parse_failed: {e}",
        }
    # Coerce
    parsed.setdefault("is_relevant", False)
    parsed.setdefault("score", 0.0)
    parsed.setdefault("matched_topics", [])
    parsed.setdefault("one_line_summary_hu", "")
    parsed.setdefault("reasoning_hu", "")
    try:
        parsed["score"] = float(parsed["score"])
    except (TypeError, ValueError):
        parsed["score"] = 0.0
    parsed["score"] = max(0.0, min(1.0, parsed["score"]))
    return parsed


async def classify(state: dict, settings: Settings) -> dict:
    """Classify every bekezdés. Keep only relevant ones."""
    bekezdes_by_issue: dict[str, list[dict]] = state.get("bekezdes_by_issue", {})
    if not bekezdes_by_issue:
        logger.info("No bekezdések to classify — skipping classify node")
        return {"classified": [], "relevant": []}

    # Flatten to (issue, bekezdes) tuples
    items: list[tuple[dict, dict]] = []
    for issue_id, bekezdes_list in bekezdes_by_issue.items():
        issue_dict = next((i for i in state["issues"] if i["issue_id"] == issue_id), {})
        for b in bekezdes_list:
            items.append((issue_dict, b))

    logger.info("Classifying %d bekezdések (threshold=%.2f)…", len(items), settings.relevance_threshold)
    llm = get_classifier()

    classified: list[dict] = []
    relevant: list[dict] = []
    parse_failures = 0

    # Sequential (keeps the LLM rate in check). Parallelize if you have headroom.
    for issue_dict, b in items:
        result = await _classify_one(llm, b)
        record = {
            "issue_id": issue_dict.get("issue_id", ""),
            "issue_number": issue_dict.get("number", ""),
            "issue_date": issue_dict.get("date", ""),
            "anchor": b["anchor"],
            "text": b["text"],
            "indokolas_url": b.get("indokolas_url"),
            "indokolas_text": b.get("indokolas_text", ""),
            **result,
        }
        classified.append(record)
        if record.get("is_relevant") and record.get("score", 0.0) >= settings.relevance_threshold:
            relevant.append(record)
        if record.get("error"):
            parse_failures += 1

    logger.info(
        "Classified %d / relevant %d / parse-failures %d",
        len(classified), len(relevant), parse_failures,
    )
    return {"classified": classified, "relevant": relevant}


__all__ = ["classify"]
