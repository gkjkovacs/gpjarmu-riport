"""Tests for the .eml builder."""
from __future__ import annotations

import email
from datetime import date
from pathlib import Path

import pytest

from gpjarmu_riport.config import LLMProvider, Settings
from gpjarmu_riport.email import build_eml, render_and_save


def _settings() -> Settings:
    return Settings(
        llm_provider=LLMProvider.OPENAI,
        llm_api_key="test-key",
        email_from="test@localhost",
        email_to="user@localhost",
        email_subject_prefix="[Test riport]",
        output_dir=Path("/tmp/gpjarmu-test"),
    )


def test_build_eml_multipart() -> None:
    s = _settings()
    msg = build_eml(
        run_date="2026-07-02",
        lookback_start="2026-06-02",
        lookback_end="2026-07-02",
        issues_scanned=10,
        new_items_count=1,
        grouped_issues=[{
            "number": "2026. évi 83. szám",
            "date": "2026-07-01",
            "items": [{
                "anchor": "12. § (3)",
                "one_line_summary_hu": "A cégautóadó mértéke 2026. január 1-jétől emelkedik.",
                "score": 0.82,
                "matched_topics": ["cégautóadó"],
                "expansion_hu": "A bekezdés a cégautóadóról szóló törvény 3. §-át módosítja: a havi fix adó 18 000 Ft-ról 19 500 Ft-ra emelkedik.",
                "key_dates_hu": ["2026. január 1."],
                "action_items_hu": ["Frissíteni a havi költségvetési tervet."],
                "indokolas_url": "https://magyarkozlony.hu/dokumentumok/abc/indokolas",
            }],
        }],
        settings=s,
    )
    assert msg.is_multipart()
    parts = list(msg.walk())
    ctypes = [p.get_content_type() for p in parts]
    assert "text/plain" in ctypes
    assert "text/html" in ctypes
    assert "1 új változás" in msg["Subject"]
    assert "[Test riport]" in msg["Subject"]


def test_build_eml_empty() -> None:
    s = _settings()
    msg = build_eml(
        run_date="2026-07-02",
        lookback_start="2026-06-02",
        lookback_end="2026-07-02",
        issues_scanned=10,
        new_items_count=0,
        grouped_issues=[],
        settings=s,
    )
    assert "0 új változás" in msg["Subject"]
    html = next(p for p in msg.walk() if p.get_content_type() == "text/html")
    body = html.get_payload(decode=True).decode(html.get_content_charset())
    assert "nem találtam" in body


def test_render_and_save_writes_file(tmp_path: Path) -> None:
    s = _settings()
    s.output_dir = tmp_path
    out = render_and_save(
        output_dir=tmp_path,
        run_date="2026-07-02",
        lookback_start="2026-06-02",
        lookback_end="2026-07-02",
        issues_scanned=10,
        new_items_count=1,
        grouped_issues=[{
            "number": "2026. évi 83. szám",
            "date": "2026-07-01",
            "items": [{
                "anchor": "12. § (3)",
                "one_line_summary_hu": "Teszt.",
                "score": 0.82,
                "matched_topics": ["cégautóadó"],
                "expansion_hu": "Teszt bővítés.",
                "key_dates_hu": [],
                "action_items_hu": [],
                "indokolas_url": None,
            }],
        }],
        settings=s,
    )
    assert out.exists()
    assert out.suffix == ".eml"
    raw = out.read_bytes()
    msg = email.message_from_bytes(raw)
    assert "Teszt." in str(msg)
