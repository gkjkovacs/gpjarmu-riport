"""
High-level mailer: turn the report into a properly-formatted email.

Three modes, selected via settings flags:

1. **Body mode** (smtp_attachment=False) — the .txt report is the email
   body. The recipient sees the report inline.

2. **Single attachment mode** (smtp_attachment=True, smtp_html_attachment=False)
   — a short cover + .txt as the only attachment. Default for clients that
   prefer plain text.

3. **Dual attachment mode** (smtp_attachment=True, smtp_html_attachment=True,
   the default) — same cover + both .txt AND .html as attachments. The
   .html is generated on-the-fly via the Jinja2 template, so it always
   matches the .txt content. Outlook, Gmail, and Apple Mail render the
   .html with clickable Közlöny links and inline badges; any plain-text
   client falls back to the .txt.

The email is built with Python's stdlib `email.message.EmailMessage`
so the only SMTP dep is the stdlib `smtplib` — no extra packages.
"""

from __future__ import annotations

import logging
from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime, timezone
from pathlib import Path

from ..config import Settings
from .eml_builder import render_html

logger = logging.getLogger(__name__)


def build_report_email(
    *,
    report_text: str,
    run_date: str,
    lookback_start: str,
    lookback_end: str,
    issues_scanned: int,
    new_items_count: int,
    grouped_issues: list[dict],
    report_path: Path | None,
    settings: Settings,
) -> EmailMessage:
    """
    Build an EmailMessage from the structured report.

    The .txt body is always required (it powers the cover, the body-only
    mode, and the .txt attachment). When smtp_html_attachment is true and
    we're in attachment mode, the HTML is rendered from grouped_issues via
    the same Jinja2 template that powers the HTML report.

    The HTML is *not* saved to disk — it's generated on-the-fly and only
    sent as an attachment (no extra file in output/).
    """
    subject = (
        f"{settings.email_subject_prefix} {run_date} "
        f"\u2013 {new_items_count} új változás"
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.email_from
    msg["To"] = settings.email_to
    msg["Date"] = format_datetime(datetime.now(timezone.utc))

    if settings.smtp_attachment and report_path is not None:
        # Cover + .txt (+ optional .html) attachments
        cover = _build_cover(run_date, new_items_count, report_path,
                            has_html=settings.smtp_html_attachment)
        msg.set_content(cover, subtype="plain", charset="utf-8")
        msg.add_attachment(
            report_text.encode("utf-8"),
            maintype="text",
            subtype="plain",
            filename=report_path.name,
        )
        if settings.smtp_html_attachment:
            html_body = render_html(
                run_date=run_date,
                lookback_start=lookback_start,
                lookback_end=lookback_end,
                issues_scanned=issues_scanned,
                new_items_count=new_items_count,
                grouped_issues=grouped_issues,
                relevance_threshold=settings.relevance_threshold,
            )
            html_name = report_path.stem + ".html"
            msg.add_attachment(
                html_body.encode("utf-8"),
                maintype="text",
                subtype="html",
                filename=html_name,
            )
            logger.info(
                "Built email with dual attachments: %s (%d B) + %s (%d B)",
                report_path.name, len(report_text),
                html_name, len(html_body),
            )
        else:
            logger.info(
                "Built email with single .txt attachment: %s (%d bytes)",
                report_path.name, len(report_text),
            )
    else:
        # Full report in the body (plain text)
        msg.set_content(report_text, subtype="plain", charset="utf-8")
        logger.info(
            "Built email with full report in body (%d bytes)", len(report_text),
        )

    return msg


def _build_cover(
    run_date: str,
    new_items_count: int,
    report_path: Path,
    has_html: bool,
) -> str:
    """The short text the recipient sees before opening the attachments."""
    if has_html:
        attach_line = (
            f"A részleteket két formátumban csatoltuk:\n"
            f"  - {report_path.name} (sima szöveg, bármilyen kliensben olvasható)\n"
            f"  - {report_path.stem}.html (színes, kattintható linkek, "
            f"Outlook/Gmail/Webmail kliensben ajánlott)"
        )
    else:
        attach_line = f"Részletek a mellékelt fájlban: {report_path.name}"

    return (
        f"Céges Gépjármű Havi Riport — {run_date}\n"
        f"\n"
        f"Ebben a hónapban {new_items_count} új, a céges gépjárműveket "
        f"érintő jogszabályváltozás jelent meg a Magyar Közlönyben.\n"
        f"\n"
        f"{attach_line}\n"
        f"\n"
        f"--\n"
        f"Automatikusan generálva · gpjarmu-riport\n"
    )


__all__ = ["build_report_email"]
