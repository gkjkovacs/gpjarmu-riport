"""
Graph node: classify

For every bekezdés across all fetched issues, ask the LLM to score
relevance (0.00–1.00) against the "HR középvállalati (~200 fő)" taxonomy.
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

# Hungarian HR-keywords that *might* be relevant for a ~200 fős középvállalat.
# Hungarian has productive suffixation (-k, -t, -nak/-nek, -ra/-re, -val/-vel,
# -i, -beli, -ás/-és, ...), so each keyword is followed by an optional
# Hungarian-suffix run [a-záéíóöőúüű]*. We keep the word boundary BEFORE
# the keyword (so "automatikus" still won't match "munka") and only loosen
# it AFTER. We use a small set of stems and let suffixation cover the rest.
_KEYWORD_PATTERN = re.compile(
    r"\b("
    # --- 1. Munkaviszony, Mt. ---
    r"munka[a-záéíóöőúüű]*|munkaviszony[a-záéíóöőúüű]*|"
    r"munkaszerződés[a-záéíóöőúüű]*|munkáltató[a-záéíóöőúüű]*|"
    r"munkavállaló[a-záéíóöőúüű]*|munkavégzés[a-záéíóöőúüű]*|"
    r"munkaviszony[a-záéíóöőúüű]*|munkabér[a-záéíóöőúüű]*|"
    r"próbaidő[a-záéíóöőúüű]*|felmond[a-záéíóöőúüű]*|"
    r"alkalmazott[a-záéíóöőúüű]*|alkalmaz[a-záéíóöőúüű]*|"
    r"foglalkoztat[a-záéíóöőúüű]*|foglalkoztató[a-záéíóöőúüű]*|"
    r"jogviszony[a-záéíóöőúüű]*|"
    # --- 2. Bér, SZJA, szocho ---
    r"bér[a-záéíóöőúüű]*|személyi jövedelemadó[a-záéíóöőúüű]*|"
    r"szja[a-záéíóöőúüű]*|szocho[a-záéíóöőúüű]*|"
    r"szociális hozzájárulási adó[a-záéíóöőúüű]*|"
    r"minimálbér[a-záéíóöőúüű]*|garantált bérminimum[a-záéíóöőúüű]*|"
    r"bérminimum[a-záéíóöőúüű]*|bérköltség[a-záéíóöőúüű]*|"
    r"bérszámfejtés[a-záéíóöőúüű]*|béren kívüli juttatás[a-záéíóöőúüű]*|"
    r"bérjövedelem[a-záéíóöőúüű]*|"
    # --- 3. Cafeteria, SZÉP ---
    r"cafeteria[a-záéíóöőúüű]*|szép-kártya[a-záéíóöőúüű]*|"
    r"szépkártya[a-záéíóöőúüű]*|széchenyi pihenő[a-záéíóöőúüű]*|"
    r"rekreációs keret[a-záéíóöőúüű]*|iskolakezdési támogatás[a-záéíóöőúüű]*|"
    r"erzsébet[a-záéíóöőúüű]*|önkéntes (pénztár|nyugdíjpénztár)[a-záéíóöőúüű]*|"
    r"lakáscélú támogatás[a-záéíóöőúüű]*|"
    # --- 4. Munkaidő ---
    r"munkaidő[a-záéíóöőúüű]*|munkaidőkeret[a-záéíóöőúüű]*|"
    r"túlóra[a-záéíóöőúüű]*|túlmunka[a-záéíóöőúüű]*|"
    r"pihenőidő[a-záéíóöőúüű]*|pihenőnap[a-záéíóöőúüű]*|"
    r"munkaszüneti nap[a-záéíóöőúüű]*|távmunka[a-záéíóöőúüű]*|"
    r"home office[a-záéíóöőúüű]*|home-office[a-záéíóöőúüű]*|"
    r"készenlét[a-záéíóöőúüű]*|éjszakai munka[a-záéíóöőúüű]*|"
    r"vasárnapi pótlék[a-záéíóöőúüű]*|munkabeosztás[a-záéíóöőúüű]*|"
    # --- 5. Szabadság ---
    r"szabadság[a-záéíóöőúüű]*|pótszabadság[a-záéíóöőúüű]*|"
    r"apaszabadság[a-záéíóöőúüű]*|szülői szabadság[a-záéíóöőúüű]*|"
    r"szülési szabadság[a-záéíóöőúüű]*|gyermekápolási[a-záéíóöőúüű]*|"
    r"betegszabadság[a-záéíóöőúüű]*|"
    # --- 6. Munkavédelem ---
    r"munkavédel[a-záéíóöőúüű]*|munkabaleset[a-záéíóöőúüű]*|"
    r"foglalkozás-egészségügy[a-záéíóöőúüű]*|foglalkozásegészségügy[a-záéíóöőúüű]*|"
    r"védőeszköz[a-záéíóöőúüű]*|kockázatértékelés[a-záéíóöőúüű]*|"
    r"munkavédelmi (képviselő|szabály)[a-záéíóöőúüű]*|"
    # --- 7. TB, nyugdíj, egészségbiztosítás ---
    r"társadalombiztosítás[a-záéíóöőúüű]*|tb-járulék[a-záéíóöőúüű]*|"
    r"nyugdíjbiztosítás[a-záéíóöőúüű]*|egészségbiztosítás[a-záéíóöőúüű]*|"
    r"nyugdíj[a-záéíóöőúüű]*|táppénz[a-záéíóöőúüű]*|"
    r"csecsemőgondozási díj[a-záéíóöőúüű]*|gyermekgondozási díj[a-záéíóöőúüű]*|"
    r"gyed[a-záéíóöőúüű]*|csed[a-záéíóöőúüű]*|tb járulék[a-záéíóöőúüű]*|"
    # --- 8. Atipikus foglalkoztatás ---
    r"megbízás[a-záéíóöőúüű]*|megbízási jogviszony[a-záéíóöőúüű]*|"
    r"alkalmi munka[a-záéíóöőúüű]*|egyszerűsített foglalkoztatás[a-záéíóöőúüű]*|"
    r"diákmunka[a-záéíóöőúüű]*|diák-szövetkezet[a-záéíóöőúüű]*|"
    r"önkéntes (munka|szerződés)[a-záéíóöőúüű]*|"
    r"4 napos munkahét[a-záéíóöőúüű]*|négy napos munkahét[a-záéíóöőúüű]*|"
    # --- 9. Foglalkoztatás-támogatás, GINOP ---
    r"álláskeresési járadék[a-záéíóöőúüű]*|álláskeresési segély[a-záéíóöőúüű]*|"
    r"képzési támogatás[a-záéíóöőúüű]*|ginop[a-záéíóöőúüű]*|"
    r"munkaadói járulékkedvezmény[a-záéíóöőúüű]*|"
    r"munkahelyvédelmi akcióterv[a-záéíóöőúüű]*|"
    r"rehabilitációs hatóság[a-záéíóöőúüű]*|"
    r"első munkahely garancia[a-záéíóöőúüű]*|"
    # --- 10. Külföldi munkavállalók ---
    r"munkavállalási engedély[a-záéíóöőúüű]*|"
    r"munkavállalási jogosultság[a-záéíóöőúüű]*|"
    r"blue card[a-záéíóöőúüű]*|szezonális munkavállal[a-záéíóöőúüű]*|"
    r"kirendelés[a-záéíóöőúüű]*|külföldi munkavállaló[a-záéíóöőúüű]*|"
    r"harmadik országbeli[a-záéíóöőúüű]*|tartózkodási engedély[a-záéíóöőúüű]*|"
    # --- 11. Esélyegyenlőség ---
    r"esélyegyenlőség[a-záéíóöőúüű]*|egyenlő bánásmód[a-záéíóöőúüű]*|"
    r"diszkrimináció[a-záéíóöőúüű]*|akadálymentesítés[a-záéíóöőúüű]*|"
    r"fogyatékossággal élő[a-záéíóöőúüű]*|fogyatékos munkavállaló[a-záéíóöőúüű]*|"
    r"védett tulajdonság[a-záéíóöőúüű]*|"
    # --- 12. Rehabilitációs hozzájárulás ---
    r"rehabilitációs hozzájárulás[a-záéíóöőúüű]*|"
    r"megváltozott munkaképesség[a-záéíóöőúüű]*|"
    r"megváltozott munkaképességű[a-záéíóöőúüű]*|"
    r"akkreditált foglalkoztató[a-záéíóöőúüű]*|"
    # --- 13. Hatóság, GDPR munkaügyi, visszaélés-bejelentés ---
    r"munkaügyi (hatóság|ellenőrzés|felügyelőség)[a-záéíóöőúüű]*|"
    r"gdpr[a-záéíóöőúüű]*|adatkezelés[a-záéíóöőúüű]*|"
    r"adatvédelmi[a-záéíóöőúüű]*|visszaélés-bejelentés[a-záéíóöőúüű]*|"
    r"belső visszaélés-bejelentési rendszer[a-záéíóöőúüű]*|"
    r"whistleblowing[a-záéíóöőúüű]*|"
    # --- 14. Üzemi tanács, szakszervezet ---
    r"üzemi tanács[a-záéíóöőúüű]*|szakszervezet[a-záéíóöőúüű]*|"
    r"kollektív szerződés[a-záéíóöőúüű]*|"
    r"érdekegyeztetés[a-záéíóöőúüű]*|sztrájk[a-záéíóöőúüű]*|"
    r"üzemi megbízott[a-záéíóöőúüű]*|"
    # --- Generic catch-alls (use carefully — they cause false positives if too loose) ---
    r"munkajog[a-záéíóöőúüű]*|munkajogi[a-záéíóöőúüű]*|"
    r"hr[a-záéíóöőúüű]*|humánerőforrás[a-záéíóöőúüű]*"
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
