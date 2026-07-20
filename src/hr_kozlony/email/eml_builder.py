"""
Text report builder.

Takes a structured list of new items and produces a plain UTF-8 text file
with the monthly corporate-vehicle regulatory report.

History: this used to produce a multipart/alternative .eml (text + HTML)
for SMTP delivery. We now produce a simple .txt file — the user reads it
directly (or the Windows Task Scheduler can attach it to an email later).
The HTML body and SMTP transport are kept as a future option but no
longer part of the main render path.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import Settings

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def _get_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _html_to_text(html: str) -> str:
    """Crude HTML→text for the text/plain alternative.

    Kept as a fallback utility. In production we build the text body
    directly from the structured data via build_text_report(), which
    gives much better control over whitespace, separator lines, and
    section breaks.
    """
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>|</div>|</li>|</h\d>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&middot;", " · ")
        .replace("&rarr;", " -> ")
        .replace("&ndash;", "-")
        .replace("&sect;", "§")
        .replace("&ge;", ">=")
    )
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _build_text_body(
    *,
    run_date: str,
    lookback_start: str,
    lookback_end: str,
    issues_scanned: int,
    new_items_count: int,
    grouped_issues: list[dict[str, Any]],
    relevance_threshold: float,
) -> str:
    """Build the report body from the structured data.

    Produces a plain-text report with:
    - 72-char separator rules between issues
    - 4-space indent for item details
    - Bullet list for action items
    - Clean newlines between every field
    - A header (run_date, lookback window, issue count) and footer
      (source, threshold, topic)
    """
    lines: list[str] = []
    sep = "=" * 72

    lines.append("HR Középvállalati Havi Riport")
    lines.append(f"HR Középvállalati — Magyar Közlöny Havi Riport — {run_date}")
    lines.append("")
    lines.append(
        f"Futtatás dátuma: {run_date}\n"
        f"Lookback: {lookback_start} -> {lookback_end}\n"
        f"Feldolgozott lapszámok: {issues_scanned}\n"
        f"Új változások: {new_items_count}"
    )
    lines.append(sep)

    if new_items_count == 0:
        lines.append(
            "Ebben a futásban nem találtam új, a HR területét (munkajog, bér, "
            "juttatás, foglalkoztatás, munkavédelem) érintő bekezdést a Magyar Közlönyben."
        )
        lines.append(f"A figyelt időablak: {lookback_start} - {lookback_end}.")
    else:
        for issue in grouped_issues:
            lines.append("")
            # The scraper's `number` field already includes the "Magyar Közlöny"
            # prefix (e.g. "Magyar Közlöny 2026. évi 81. szám"). We only prepend
            # it when the field is empty or uses a short slug like "2026/81".
            number = issue["number"]
            if not number.startswith("Magyar Közlöny"):
                number = f"Magyar Közlöny {number}"
            lines.append(f"{number} ({issue['date']})")
            if issue.get("url"):
                lines.append(
                    f"Ezen a linken éred el ezt a közlönyt: {issue['url']}"
                )
            lines.append("-" * 72)
            for item in issue["items"]:
                lines.append("")
                lines.append(f"§ {item['anchor']} — {item['one_line_summary_hu']}")
                lines.append(f"  Relevancia: {item['score']:.2f}")
                topics = ", ".join(item.get("matched_topics") or []) or "(nincs)"
                lines.append(f"  Témák: {topics}")
                lines.append("")
                lines.append(f"  {item['expansion_hu']}")
                if item.get("key_dates_hu"):
                    lines.append("")
                    lines.append(f"  Határidők: {', '.join(item['key_dates_hu'])}")
                if item.get("action_items_hu"):
                    lines.append("")
                    lines.append("  Teendők:")
                    for a in item["action_items_hu"]:
                        lines.append(f"    - {a}")
                if item.get("indokolas_url"):
                    lines.append("")
                    lines.append(f"  Indokolás: {item['indokolas_url']}")

    lines.append("")
    lines.append(sep)
    lines.append(
        "Automatikusan generálva · Forrás: https://magyarkozlony.hu · "
        f"Szűrési küszöb: relevancia >= {relevance_threshold:.2f} (tág) · "
        "Témakör: HR középvállalati (~200 fő)"
    )
    lines.append("")
    lines.append(f"Generálva: {datetime.now(timezone.utc).isoformat()}")

    return "\n".join(lines)


def render_html(
    *,
    run_date: str,
    lookback_start: str,
    lookback_end: str,
    issues_scanned: int,
    new_items_count: int,
    grouped_issues: list[dict[str, Any]],
    relevance_threshold: float,
) -> str:
    """Render the HTML body from the Jinja2 template.

    Kept for future use (e.g. if we re-enable SMTP). Not used by the
    main .txt render path anymore.
    """
    env = _get_env()
    tpl = env.get_template("eml-template.html.j2")
    return tpl.render(
        run_date=run_date,
        lookback_start=lookback_start,
        lookback_end=lookback_end,
        issues_scanned=issues_scanned,
        new_items_count=new_items_count,
        grouped_issues=grouped_issues,
        relevance_threshold=relevance_threshold,
    )


def build_text_report(
    *,
    run_date: str,
    lookback_start: str,
    lookback_end: str,
    issues_scanned: int,
    new_items_count: int,
    grouped_issues: list[dict[str, Any]],
    settings: Settings,
) -> str:
    """Build the text report body from the structured data."""
    return _build_text_body(
        run_date=run_date,
        lookback_start=lookback_start,
        lookback_end=lookback_end,
        issues_scanned=issues_scanned,
        new_items_count=new_items_count,
        grouped_issues=grouped_issues,
        relevance_threshold=settings.relevance_threshold,
    )


def save_text_report(text: str, output_path: Path) -> Path:
    """Write the text report to a .txt file (UTF-8)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    logger.info("Saved report: %s (%d bytes)", output_path, output_path.stat().st_size)
    return output_path


def render_and_save_report(
    *,
    output_dir: Path,
    run_date: str,
    lookback_start: str,
    lookback_end: str,
    issues_scanned: int,
    new_items_count: int,
    grouped_issues: list[dict[str, Any]],
    settings: Settings,
) -> Path:
    """Convenience: build the text report + save it to disk in one call."""
    text = build_text_report(
        run_date=run_date,
        lookback_start=lookback_start,
        lookback_end=lookback_end,
        issues_scanned=issues_scanned,
        new_items_count=new_items_count,
        grouped_issues=grouped_issues,
        settings=settings,
    )
    return save_text_report(text, output_dir / f"hr-kozlony-{run_date}.txt")


__all__ = [
    "build_text_report",
    "save_text_report",
    "render_and_save_report",
    "render_html",  # kept for future SMTP re-enablement
    "_build_text_body",
    "_html_to_text",  # kept as a fallback utility
]
