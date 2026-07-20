"""Tests for the relevance classifier node — keyword pre-filter logic."""
from __future__ import annotations

from hr_kozlony.graph.nodes.classify import (
    _coerce_classifier_result,
    _keyword_match,
    _safe_parse_json,
)


def test_keyword_match_finds_munkavállaló() -> None:
    b = {"text": "A munkavállaló jogosult a szabadságra a Munka törvénykönyve szerint.", "indokolas_text": ""}
    assert _keyword_match(b) is True


def test_keyword_match_finds_in_indokolas_only() -> None:
    b = {"text": "Semmi köze a témához.", "indokolas_text": "Indokolás: a munkavállalókat érinti."}
    assert _keyword_match(b) is True


def test_keyword_match_rejects_unrelated() -> None:
    # "A nyugdíjak emeléséről szóló törvény." — IS a HR-téma, ezért a
    # HR-listás kulcsszavak (nyugdíjak) találnak. A teszt azt várja, hogy
    # a kulcsszó-szűrő NEM dobja el, a döntés a LLM-re marad.
    b = {"text": "A nyugdíjak emeléséről szóló törvény.", "indokolas_text": ""}
    assert _keyword_match(b) is True


def test_keyword_match_handles_case_and_accents() -> None:
    b = {"text": "MUNKAVÁLLALÓK esetében a szabály alkalmazandó.", "indokolas_text": ""}
    assert _keyword_match(b) is True


def test_keyword_match_handles_word_boundary() -> None:
    # "automatikus" should NOT match "munka" — word boundary \b check
    b = {"text": "Az automatikus rendszer engedélyezve van.", "indokolas_text": ""}
    assert _keyword_match(b) is False


def test_keyword_match_handles_empty() -> None:
    assert _keyword_match({"text": "", "indokolas_text": ""}) is False


# --- JSON parse + coerce helpers (used by the repair-pass in _classify_one) ---


def test_safe_parse_json_accepts_clean_json() -> None:
    raw = '{"is_relevant": true, "score": 0.7, "matched_topics": ["bér", "szja"], "one_line_summary_hu": "x", "reasoning_hu": "y"}'
    parsed = _safe_parse_json(raw)
    assert parsed is not None
    assert parsed["is_relevant"] is True
    assert parsed["score"] == 0.7


def test_safe_parse_json_strips_markdown_fences() -> None:
    raw = '```json\n{"is_relevant": false, "score": 0.0, "matched_topics": [], "one_line_summary_hu": "", "reasoning_hu": ""}\n```'
    parsed = _safe_parse_json(raw)
    assert parsed is not None
    assert parsed["is_relevant"] is False


def test_safe_parse_json_returns_none_for_broken_quote() -> None:
    # The exact failure mode from the live run: ASCII " inside a Hungarian quoted
    # title ("A méltányosság elve") terminates the JSON string early.
    raw = (
        '{"is_relevant": false, "score": 0.0, "matched_topics": [], '
        '"one_line_summary_hu": "A Kormány határozata a "méltányosság '
        'elve" alkalmazásáról.", '
        '"reasoning_hu": "A bekezdés"}'
    )
    assert _safe_parse_json(raw) is None


def test_safe_parse_json_returns_none_for_literal_newline() -> None:
    # A raw newline inside a string value is also invalid JSON.
    raw = '{"is_relevant": false, "score": 0.0, "matched_topics": [], "one_line_summary_hu": "line1\nline2", "reasoning_hu": "x"}'
    assert _safe_parse_json(raw) is None


def test_coerce_classifier_result_clamps_score() -> None:
    out = _coerce_classifier_result({"score": 1.7, "is_relevant": True})
    assert out["score"] == 1.0


def test_coerce_classifier_result_fills_defaults() -> None:
    out = _coerce_classifier_result({})
    assert out["is_relevant"] is False
    assert out["score"] == 0.0
    assert out["matched_topics"] == []
    assert out["one_line_summary_hu"] == ""
    assert out["reasoning_hu"] == ""
