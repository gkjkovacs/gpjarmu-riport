"""Tests for the expander node — JSON parse + coerce helpers and graceful fallback."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from gpjarmu_riport.graph.nodes.expand import (
    _coerce_expander_result,
    _expand_one,
    _extract_json,
    _safe_parse_json,
)


def test_extract_json_accepts_clean_json() -> None:
    raw = '{"expansion_hu": "x", "key_dates_hu": ["2026. jan. 1."], "action_items_hu": ["y"]}'
    parsed = _extract_json(raw)
    assert parsed["expansion_hu"] == "x"
    assert parsed["key_dates_hu"] == ["2026. jan. 1."]


def test_extract_json_strips_markdown_fences() -> None:
    raw = '```json\n{"expansion_hu": "x", "key_dates_hu": [], "action_items_hu": []}\n```'
    parsed = _extract_json(raw)
    assert parsed["expansion_hu"] == "x"


def test_extract_json_raises_on_garbage() -> None:
    with pytest.raises((ValueError, Exception)):
        _extract_json("not json at all, no braces")


def test_safe_parse_json_returns_none_for_broken_quote() -> None:
    # The exact failure mode from the live run: ASCII " inside a Hungarian quoted
    # title terminates the JSON string early, then a literal newline follows.
    raw = (
        '{"expansion_hu": "Kormányhatározat a közösségi közlekedés versenyképességéről\n'
        'és az országos közlekedésszervező, valamint gördülőállo", "key_dates_hu": [], '
        '"action_items_hu": []}'
    )
    assert _safe_parse_json(raw) is None


def test_safe_parse_json_returns_none_for_literal_newline() -> None:
    raw = '{"expansion_hu": "line1\nline2", "key_dates_hu": [], "action_items_hu": []}'
    assert _safe_parse_json(raw) is None


def test_coerce_expander_result_fills_defaults() -> None:
    out = _coerce_expander_result({}, fallback_one_line="FB")
    assert out["expansion_hu"] == "FB"
    assert out["key_dates_hu"] == []
    assert out["action_items_hu"] == []


def test_coerce_expander_result_normalises_wrong_types() -> None:
    # If the LLM returns a string instead of a list, the coerce must fix it.
    out = _coerce_expander_result(
        {"expansion_hu": "x", "key_dates_hu": "oops", "action_items_hu": 42},
        fallback_one_line="FB",
    )
    assert out["key_dates_hu"] == []
    assert out["action_items_hu"] == []


@pytest.mark.asyncio
async def test_expand_one_succeeds_on_clean_json() -> None:
    llm = MagicMock()
    llm.ainvoke = _async_iter([
        '{"expansion_hu": "A bekezdés a cégautóadót módosítja.", "key_dates_hu": ["2026.01.01."], "action_items_hu": ["x"]}'
    ])
    item = {
        "anchor": "12. §", "score": 0.7, "matched_topics": ["cégautóadó"],
        "one_line_summary_hu": "rövid", "text": "...", "indokolas_text": "",
        "indokolas_url": None,
    }
    out = await _expand_one(llm, item)
    assert "error" not in out
    assert out["expansion_hu"].startswith("A bekezdés")
    assert out["key_dates_hu"] == ["2026.01.01."]


@pytest.mark.asyncio
async def test_expand_one_repairs_malformed_json() -> None:
    # First call returns broken JSON (ASCII " inside string + literal newline);
    # second call (repair) returns valid JSON.
    llm = MagicMock()
    bad = (
        '{"expansion_hu": "Kormányhatározat a közlekedésről\nés a "gördülőállomány" fejlesztéséről.", '
        '"key_dates_hu": [], "action_items_hu": []}'
    )
    good = '{"expansion_hu": "A kormányhatározat a közlekedésről szól.", "key_dates_hu": [], "action_items_hu": []}'
    llm.ainvoke = _async_iter([bad, good])
    item = {
        "anchor": "5. §", "score": 0.6, "matched_topics": ["közlekedés"],
        "one_line_summary_hu": "FB", "text": "...", "indokolas_text": "",
        "indokolas_url": None,
    }
    out = await _expand_one(llm, item)
    assert "error" not in out
    assert out["expansion_hu"] == "A kormányhatározat a közlekedésről szól."


@pytest.mark.asyncio
async def test_expand_one_falls_back_after_double_failure() -> None:
    # Both attempts return broken JSON — the item still survives, with the
    # one-line summary as expansion and parse_failed_after_repair flag.
    llm = MagicMock()
    bad = '{"expansion_hu": "broken\n"quote", "key_dates_hu": [], "action_items_hu": []}'
    llm.ainvoke = _async_iter([bad, bad])
    item = {
        "anchor": "7. §", "score": 0.55, "matched_topics": [],
        "one_line_summary_hu": "FB-summary", "text": "...", "indokolas_text": "",
        "indokolas_url": None,
    }
    out = await _expand_one(llm, item)
    assert out["expansion_hu"] == "FB-summary"
    assert out["error"] == "parse_failed_after_repair"
    assert out["key_dates_hu"] == []
    assert out["action_items_hu"] == []


def _async_iter(values: list[str]):
    """Build an async function that returns an AIMessage-like object for each value.

    The expander reads response.content — a plain string wouldn't have that attr.
    """
    it = iter(values)

    class _Msg:
        def __init__(self, content: str) -> None:
            self.content = content

    async def _ainvoke(*_args, **_kwargs):
        return _Msg(next(it))

    return _ainvoke
