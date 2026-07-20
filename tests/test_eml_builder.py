"""Tests for the text report builder."""
from __future__ import annotations

from pathlib import Path

from hr_kozlony.config import LLMProvider, Settings
from hr_kozlony.email import build_text_report, render_and_save_report


def _settings() -> Settings:
    return Settings(
        llm_provider=LLMProvider.OPENAI,
        llm_api_key="test-key",
        email_from="test@localhost",
        email_to="user@localhost",
        email_subject_prefix="[Test riport]",
        output_dir=Path("/tmp/hr-kozlony-test"),
    )


def _sample_grouped_issues() -> list[dict]:
    return [{
        "number": "2026. évi 83. szám",
        "date": "2026-07-01",
        "url": "https://magyarkozlony.hu/dokumentumok/abc123/megtekintes",
        "items": [{
            "anchor": "12. § (3)",
            "one_line_summary_hu": "A 25 év alatti munkavállalók SZJA-mentessége 2026. január 1-jétől kiterjed.",
            "score": 0.82,
            "matched_topics": ["bér", "szja"],
            "expansion_hu": (
                "A bekezdés az Szja tv. 29/A. §-át módosítja: a 25 év alatti munkavállalók "
                "SZJA-mentessége a havi 499 952 Ft-os határ helyett 5,5 millió Ft-os "
                "jövedelemhatárig terjed 2026. január 1-jétől."
            ),
            "key_dates_hu": ["2026. január 1."],
            "action_items_hu": ["HR vezetőknek: felülvizsgálni a 25 év alatti munkavállalók bérszámfejtését."],
            "indokolas_url": "https://magyarkozlony.hu/dokumentumok/abc/indokolas",
        }],
    }]


def test_build_text_report_includes_summary_and_expansion() -> None:
    body = build_text_report(
        run_date="2026-07-02",
        lookback_start="2026-06-02",
        lookback_end="2026-07-02",
        issues_scanned=10,
        new_items_count=1,
        grouped_issues=_sample_grouped_issues(),
        settings=_settings(),
    )
    # Header
    assert "HR Középvállalati Havi Riport" in body
    assert "Futtatás dátuma: 2026-07-02" in body
    assert "Új változások: 1" in body
    # Anchor + one-line summary
    assert "§ 12. § (3)" in body
    assert "A 25 év alatti munkavállalók SZJA-mentessége" in body
    # Expansion
    assert "az Szja tv. 29/A. §-át módosítja" in body
    # Key dates
    assert "Határidők: 2026. január 1." in body
    # Action items (with bullet)
    assert "  Teendők:" in body
    assert "    - HR vezetőknek:" in body
    # Indokolás URL
    assert "https://magyarkozlony.hu/dokumentumok/abc/indokolas" in body
    # Per-issue link (Közlöny URL)
    assert "Ezen a linken éred el ezt a közlönyt" in body
    assert "https://magyarkozlony.hu/dokumentumok/abc123/megtekintes" in body
    # Footer
    assert "HR középvállalati" in body


def test_build_text_report_includes_issue_link() -> None:
    """The Közlöny link should appear right under the issue header."""
    body = build_text_report(
        run_date="2026-07-02",
        lookback_start="2026-06-02",
        lookback_end="2026-07-02",
        issues_scanned=1,
        new_items_count=1,
        grouped_issues=_sample_grouped_issues(),
        settings=_settings(),
    )
    # The link must appear AFTER the issue header and BEFORE the items
    issue_header_pos = body.find("Magyar Közlöny 2026. évi 83. szám (2026-07-01)")
    link_pos = body.find("Ezen a linken éred el ezt a közlönyt")
    first_item_pos = body.find("§ 12. § (3)")
    assert issue_header_pos != -1
    assert link_pos != -1
    assert first_item_pos != -1
    assert issue_header_pos < link_pos < first_item_pos, (
        f"link not between header and items: "
        f"header={issue_header_pos} link={link_pos} item={first_item_pos}"
    )


def test_build_text_report_skips_link_when_url_missing() -> None:
    """When the scraper can't produce a megtekintes_url, the report must
    still render cleanly without the link line."""
    issues = _sample_grouped_issues()
    issues[0].pop("url", None)  # simulate missing URL
    body = build_text_report(
        run_date="2026-07-02",
        lookback_start="2026-06-02",
        lookback_end="2026-07-02",
        issues_scanned=1,
        new_items_count=1,
        grouped_issues=issues,
        settings=_settings(),
    )
    assert "Ezen a linken éred el ezt a közlönyt" not in body
    # The rest of the report is still complete
    assert "Magyar Közlöny 2026. évi 83. szám" in body
    assert "§ 12. § (3)" in body


def test_build_text_report_separates_topics_with_comma() -> None:
    """Regression: when the LLM returns multiple topic labels, they must
    be separated by ', ' in the plain-text view, not concatenated."""
    body = build_text_report(
        run_date="2026-07-02",
        lookback_start="2026-06-02",
        lookback_end="2026-07-02",
        issues_scanned=1,
        new_items_count=1,
        grouped_issues=[{
            "number": "X",
            "date": "2026-07-01",
            "items": [{
                "anchor": "1. §",
                "one_line_summary_hu": "x",
                "score": 0.6,
                "matched_topics": ["bér", "szja", "cafeteria"],
                "expansion_hu": "y",
                "key_dates_hu": [],
                "action_items_hu": [],
                "indokolas_url": None,
            }],
        }],
        settings=_settings(),
    )
    assert "Témák: bér, szja, cafeteria" in body


def test_build_text_report_empty() -> None:
    body = build_text_report(
        run_date="2026-07-02",
        lookback_start="2026-06-02",
        lookback_end="2026-07-02",
        issues_scanned=10,
        new_items_count=0,
        grouped_issues=[],
        settings=_settings(),
    )
    assert "Új változások: 0" in body
    assert "nem találtam új" in body
    assert "HR területét" in body  # HR-specific copy


def test_render_and_save_report_writes_txt(tmp_path: Path) -> None:
    s = _settings()
    s.output_dir = tmp_path
    out = render_and_save_report(
        output_dir=tmp_path,
        run_date="2026-07-02",
        lookback_start="2026-06-02",
        lookback_end="2026-07-02",
        issues_scanned=10,
        new_items_count=1,
        grouped_issues=_sample_grouped_issues(),
        settings=s,
    )
    assert out.exists()
    assert out.suffix == ".txt"
    # Verify it's a plain UTF-8 text file
    text = out.read_text(encoding="utf-8")
    assert "HR Középvállalati Havi Riport" in text
    assert "az Szja tv. 29/A. §-át módosítja" in text
    # No MIME headers should be present
    assert "Content-Type:" not in text
    assert "MIME-Version:" not in text
    assert "--===" not in text  # no MIME boundary
