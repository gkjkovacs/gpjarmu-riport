"""
Graph node: classify

For every bekezdés across all fetched issues, ask the LLM to score
relevance (0.00–1.00) against the "Gépjármű / Céges Gépjármű" taxonomy.
Keep only bekezdések with score >= RELEVANCE_THRESHOLD.

Performance optimizations:
- Keyword pre-filter: drop bekezdések that contain no relevant keyword before
  paying for an LLM call. Cuts 80-95% of API calls.
- Parallel LLM calls via asyncio.gather with a concurrency semaphore
  (CLASSIFY_CONCURRENCY, default 5) — keeps rate limit under control while
  being ~5× faster than sequential.
"""

from __future__ import annotations

import asyncio
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

# Hungarian (and some German-origin) keywords that *might* be relevant.
# Hungarian has productive suffixation (-k, -t, -nak/-nek, -ra/-re, -val/-vel,
# -i, -beli, ...), so each keyword is followed by an optional Hungarian
# suffix run. We keep the word boundary BEFORE the keyword (so "automatikus"
# still won't match "autó") and only loosen it AFTER. A few stems use
# suffixes that are not regular (e.g. "járművek" → "jármű") so those are
# listed explicitly with `(?:vek|vet|vön|vét|vek)?`.
_KEYWORD_PATTERN = re.compile(
    r"\b("
    # jármű family — irregular plurals
    r"gépjármű[veköűei]+|gépjárművek?|jármű[veköűei]+|járművek?|jármű|"
    r"gépkocsi[ké]+|gépkocsik?|"
    # autó family
    r"autó[ké]+|autók|autós[ae]k?|személygépkocsi[ké]+|szgk(?:-[a-z0-9]+)?|"
    r"tehergépkocsi[ké]+|tehergépjármű[veköűei]+|"
    # cégautó family — covers cégautó, cégautók, cégautókat, cégautónak, cégautóra, etc.
    r"cégautó[a-záéíóöőúüű]*|céges (gépjármű|autó)[a-záéíóöőúüű]*|"
    r"cégautóadó[a-záéíóöőúüű]*|cégjármű[a-záéíóöőúüű]*|"
    # flotta
    r"flotta[a-záéíóöőúüű]*|flottakezelő[a-záéíóöőúüű]*|"
    # lízing
    r"lízing[a-záéíóöőúüű]*|operatív lízing[a-záéíóöőúüű]*|pénzügyi lízing[a-záéíóöőúüű]*|"
    # biztosítás
    r"casco[a-záéíóöőúüű]*|kfgb[a-záéíóöőúüű]*|"
    r"kötelező (gépjármű|biztosítás)[a-záéíóöőúüű]*|kgfb[a-záéíóöőúüű]*|"
    # útdíj
    r"útdíj[a-záéíóöőúüű]*|hu-go[a-záéíóöőúüű]*|e-matrica[a-záéíóöőúüű]*|"
    r"ematricá[a-záéíóöőúüű]*|"
    # üzemanyag
    r"üzemanyag[a-záéíóöőúüű]*|üzemanyagköltség[a-záéíóöőúüű]*|"
    r"kilométerköltség[a-záéíóöőúüű]*|kilométerátalány[a-záéíóöőúüű]*|"
    # vezető
    r"gépjárművezető[a-záéíóöőúüű]*|gépjármű-vezető[a-záéíóöőúüű]*|"
    r"járművezető[a-záéíóöőúüű]*|cégautóvezetői[a-záéíóöőúüű]*|"
    # menetlevél, tachográf
    r"menetlevél[a-záéíóöőúüű]*|tachográf[a-záéíóöőúüű]*|"
    # haszongépjármű
    r"haszongépjármű[veköűei]*|haszongépjárművek?|"
    # zéró emissziós, elektromos, hibrid
    r"zéró emissziós[a-záéíóöőúüű]*|elektromos (jármű|autó)[a-záéíóöőúüű]*|"
    r"hibrid (jármű|autó)[a-záéíóöőúüű]*|"
    # egyéb
    r"hajtású[a-záéíóöőúüű]*|hajtóanyag[a-záéíóöőúüű]*|"
    r"áfa[a-záéíóöőúüű]*|áfás[a-záéíóöőúüű]*"
    r")",
    re.IGNORECASE,
)


def _keyword_match(b: dict[str, Any]) -> bool:
    """Return True if the bekezdés text + indokolás text contains any keyword."""
    text = (b.get("text", "") + "\n" + b.get("indokolas_text", "")).lower()
    return bool(_KEYWORD_PATTERN.search(text))


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


def _safe_parse_json(text: str) -> dict[str, Any] | None:
    """Try to extract a JSON object from the LLM response. Returns None on failure."""
    try:
        return _extract_json(text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.debug("JSON parse failed: %s — raw: %r", e, text[:200])
        return None


def _coerce_classifier_result(parsed: dict[str, Any]) -> dict[str, Any]:
    """Normalize a parsed classifier dict to our internal schema. Always returns a dict."""
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


def _build_user_message(b: dict[str, Any]) -> str:
    parts = ["Bekezdés szövege:", "<<<", b["text"].strip(), ">>>"]
    if b.get("indokolas_text", "").strip():
        parts += ["", "Indokolás (kontextus):", "<<<", b["indokolas_text"].strip(), ">>>"]
    return "\n".join(parts) + _STRICT_SUFFIX


async def _classify_one(llm, b: dict[str, Any]) -> dict[str, Any]:
    """Classify a single bekezdés. Returns parsed JSON dict.

    On JSON parse failure, we retry once with a "fix your JSON" prompt — the
    4B-class models we target occasionally produce literal newlines or
    unescaped inner quotes inside string values. A repair pass is cheaper
    than dropping the bekezdés.
    """
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
    parsed = _safe_parse_json(raw)
    if parsed is not None:
        return _coerce_classifier_result(parsed)

    # --- Repair pass: ask the model to fix the malformed JSON ---
    logger.warning(
        "Classifier returned invalid JSON (first attempt) — requesting repair. raw[:200]=%r",
        raw[:200],
    )
    repair_prompt = (
        "Your previous response was not valid JSON. Here is the raw output:\n\n"
        "<<<" + raw + ">>>\n\n"
        "Please re-emit the SAME answer as a single valid JSON object with the exact same "
        "five keys (is_relevant, score, matched_topics, one_line_summary_hu, reasoning_hu). "
        "Remember: no literal newlines inside any string, and no unescaped ASCII double-quote "
        'characters (") inside string values. Output the JSON object only — no prose, no '
        "markdown fences."
    )
    try:
        response2 = await llm.ainvoke([
            SystemMessage(content=RELEVANCE_CLASSIFIER_SYSTEM),
            HumanMessage(content=repair_prompt),
        ])
    except Exception as e:
        logger.warning("Repair LLM call failed: %s", e)
        return {
            "is_relevant": False, "score": 0.0,
            "matched_topics": [], "one_line_summary_hu": "", "reasoning_hu": "",
            "error": f"parse_failed: {type(e).__name__}: {e}",
        }
    raw2 = response2.content if isinstance(response2.content, str) else str(response2.content)
    parsed2 = _safe_parse_json(raw2)
    if parsed2 is not None:
        logger.info("Repair pass succeeded for bekezdés anchor=%r", b.get("anchor"))
        return _coerce_classifier_result(parsed2)

    logger.warning(
        "Classifier JSON still unparseable after repair. raw[:200]=%r",
        raw2[:200],
    )
    return {
        "is_relevant": False, "score": 0.0,
        "matched_topics": [], "one_line_summary_hu": "", "reasoning_hu": "",
        "error": "parse_failed_after_repair",
    }


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

    logger.info(
        "Pre-filter: %d bekezdések, scanning for keyword matches…", len(items),
    )

    if settings.keyword_filter_enabled:
        # Step 1: keyword pre-filter
        candidates = []
        skipped = 0
        for issue_dict, b in items:
            if _keyword_match(b):
                candidates.append((issue_dict, b))
            else:
                skipped += 1
    else:
        candidates = list(items)
        skipped = 0

    logger.info(
        "Keyword pre-filter: %d → %d candidates (skipped %d no-keyword bekezdések, "
        "saving %d LLM calls). Threshold=%.2f, Concurrency=%d",
        len(items), len(candidates), skipped, skipped,
        settings.relevance_threshold, settings.classify_concurrency,
    )

    if not candidates:
        return {"classified": [], "relevant": []}

    llm = get_classifier()
    sem = asyncio.Semaphore(settings.classify_concurrency)

    async def _throttled(b: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            return await _classify_one(llm, b)

    # --- Step 2: parallel classify ---
    logger.info("Classifying %d candidates in parallel…", len(candidates))
    results = await asyncio.gather(
        *(_throttled(b) for _, b in candidates),
        return_exceptions=False,
    )

    # --- Step 3: assemble + filter ---
    classified: list[dict] = []
    relevant: list[dict] = []
    parse_failures = 0

    for (issue_dict, b), result in zip(candidates, results):
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
        "Classified %d (after filter) / relevant %d / parse-failures %d "
        "(skipped %d by keyword filter)",
        len(classified), len(relevant), parse_failures, skipped,
    )
    return {"classified": classified, "relevant": relevant}


__all__ = ["classify"]
