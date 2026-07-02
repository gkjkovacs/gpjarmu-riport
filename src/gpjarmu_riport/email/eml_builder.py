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
    """Crude HTML→text for the text/plain alternative."""
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
    )
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
    text_body = _html_to_text(html_body)

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
