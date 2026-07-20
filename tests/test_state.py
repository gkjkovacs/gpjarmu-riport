"""Tests for the SQLite state DB."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from hr_kozlony.state.db import ReportedItem, StateDB


@pytest.fixture
def db(tmp_path: Path) -> StateDB:
    return StateDB(tmp_path / "test_state.db")


def _make_item(
    issue_number: str = "2026. évi 83. szám",
    anchor: str = "12. § (3)",
    issue_date: str = "2026-07-01",
    score: float = 0.82,
) -> ReportedItem:
    return ReportedItem(
        issue_number=issue_number,
        anchor=anchor,
        issue_date=issue_date,
        content_hash="abc123",
        score=score,
        matched_topics=["cégautóadó"],
        one_line_summary_hu="A cégautóadó mértéke 2026. január 1-jétől emelkedik.",
        expansion_hu="A bekezdés a cégautóadóról szóló törvény 3. §-át módosítja.",
        key_dates_hu=["2026. január 1."],
        action_items_hu=["Frissíteni a költségvetést."],
        indokolas_url="https://magyarkozlony.hu/dokumentumok/abc/indokolas",
    )


def test_init_creates_schema(tmp_path: Path) -> None:
    db = StateDB(tmp_path / "fresh.db")
    meta = db.get_run_meta()
    assert meta == {}


def test_mark_reported_inserts_and_is_idempotent(db: StateDB) -> None:
    item = _make_item()
    assert db.mark_reported(item) is True
    assert db.mark_reported(item) is False
    assert db.is_already_reported("2026. évi 83. szám", "12. § (3)") is True


def test_mark_reported_persists_all_fields(db: StateDB) -> None:
    item = _make_item()
    db.mark_reported(item)
    [fetched] = db.list_reported_in_window("2026-01-01", "2026-12-31")
    assert fetched.issue_number == item.issue_number
    assert fetched.anchor == item.anchor
    assert fetched.score == pytest.approx(0.82)
    assert fetched.matched_topics == ["cégautóadó"]
    assert fetched.key_dates_hu == ["2026. január 1."]


def test_issue_progress(db: StateDB) -> None:
    assert db.is_issue_processed("2026. évi 83. szám") is False
    db.mark_issue_processed(
        issue_number="2026. évi 83. szám",
        issue_date="2026-07-01",
        items_classified=10,
        items_relevant=2,
    )
    assert db.is_issue_processed("2026. évi 83. szám") is True


def test_run_meta(db: StateDB) -> None:
    db.set_last_run_date(_date(2026, 7, 2))
    assert db.get_last_run_date() == _date(2026, 7, 2)
    assert db.get_run_meta()["last_run"] == "2026-07-02"


def test_bump_total_reported(db: StateDB) -> None:
    assert db.bump_total_reported(3) == 3
    assert db.bump_total_reported(2) == 5
    assert db.get_run_meta()["total_reported"] == "5"


def test_reset_clears_everything(db: StateDB) -> None:
    db.mark_reported(_make_item())
    db.mark_issue_processed("2026. évi 83. szám", "2026-07-01", 5, 1)
    db.set_last_run_date(_date(2026, 7, 2))

    db.reset()
    assert db.is_already_reported("2026. évi 83. szám", "12. § (3)") is False
    assert db.is_issue_processed("2026. évi 83. szám") is False
    assert db.get_run_meta() == {}


def _date(y, m, d):
    from datetime import date
    return date(y, m, d)
