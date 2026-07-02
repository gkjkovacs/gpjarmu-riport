"""
.eml file builder.

Takes a structured list of new items and produces a valid RFC 5322
.eml file (multipart/alternative: text/plain + text/html).

The HTML body is rendered from a Jinja2 template (templates/eml-template.html.j2);
the plain-text alternative is a crude HTML→text conversion.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
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

    Used as a fallback by tests; in production we now build the text body
    directly from the structured data via _build_text_body(), which gives
    much better control over whitespace, separator lines, and section breaks.
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
    """Build the text/plain body from the structured data, not from the HTML.

    Building text from HTML loses whitespace between elements (especially
    between adjacent <span> badges in the same line), and the result is
    hard to read. Building from structured data gives a plain-text email
    that renders cleanly in every text-only or 'prefer plain text' client.
    """
    lines: list[str] = []
    sep = "=" * 72

    lines.append("Céges Gépjármű Havi Riport")
    lines.append(f"Céges Gépjármű — Magyar Közlöny Havi Riport — {run_date}")
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
            "Ebben a futásban nem találtam új, a céges gépjármű-témakört "
            "érintő bekezdést a Magyar Közlönyben."
        )
        lines.append(f"A figyelt időablak: {lookback_start} - {lookback_end}.")
    else:
        for issue in grouped_issues:
            lines.append("")
            lines.append(f"Magyar Közlöny {issue['number']} ({issue['date']})")
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
        "Témakör: Gépjármű / Céges Gépjármű"
    )

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


def build_eml(
    *,
    run_date: str,
    lookback_start: str,
    lookback_end: str,
    issues_scanned: int,
    new_items_count: int,
    grouped_issues: list[dict[str, Any]],
    settings: Settings,
) -> EmailMessage:
    """Build an EmailMessage (multipart/alternative) without writing to disk."""
    html_body = render_html(
        run_date=run_date,
        lookback_start=lookback_start,
        lookback_end=lookback_end,
        issues_scanned=issues_scanned,
        new_items_count=new_items_count,
        grouped_issues=grouped_issues,
        relevance_threshold=settings.relevance_threshold,
    )
    # Build the text body from the structured data, not from the HTML.
    # This avoids the "words running together" problem where adjacent
    # badge <span>s have no whitespace between them in the plain-text view.
    text_body = _build_text_body(
        run_date=run_date,
        lookback_start=lookback_start,
        lookback_end=lookback_end,
        issues_scanned=issues_scanned,
        new_items_count=new_items_count,
        grouped_issues=grouped_issues,
        relevance_threshold=settings.relevance_threshold,
    )

    subject = f"{settings.email_subject_prefix} {run_date} – {new_items_count} új változás"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.email_from
    msg["To"] = settings.email_to
    msg["Date"] = format_datetime(datetime.now(timezone.utc))
    msg["Message-ID"] = f"<{uuid.uuid4()}@gpjarmu-riport.localhost>"
    msg.set_content(text_body, subtype="plain", charset="utf-8")
    msg.add_alternative(html_body, subtype="html", charset="utf-8")
    return msg


def save_eml(msg: EmailMessage, output_path: Path) -> Path:
    """Write the EmailMessage to a .eml file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(bytes(msg))
    logger.info("Saved .eml: %s (%d bytes)", output_path, output_path.stat().st_size)
    return output_path


def render_and_save(
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
    """Convenience: build + save in one call."""
    msg = build_eml(
        run_date=run_date,
        lookback_start=lookback_start,
        lookback_end=lookback_end,
        issues_scanned=issues_scanned,
        new_items_count=new_items_count,
        grouped_issues=grouped_issues,
        settings=settings,
    )
    return save_eml(msg, output_dir / f"gpjarmu-{run_date}.eml")


__all__ = [
    "build_eml",
    "save_eml",
    "render_html",
    "render_and_save",
]
