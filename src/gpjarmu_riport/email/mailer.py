"""
High-level mailer: turn a .txt report into a properly-formatted email.

Two modes:

1. **Body mode** (smtp_attachment=False) — the report text IS the email
   body. The recipient sees the report inline when they open the email.
   Best for short reports; everything is visible at a glance.

2. **Attachment mode** (smtp_attachment=True, default) — the email has
   a short cover message and the report is attached as a .txt file.
   Best for longer reports or when the user wants to archive the
   report as a file. The recipient gets both a glanceable summary
   and the full report.

The email is built using Python's stdlib `email.message.EmailMessage`
so the only SMTP dep is the stdlib `smtplib` — no extra packages.
"""

from __future__ import annotations

import logging
from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime, timezone
from pathlib import Path

from ..config import Settings

logger = logging.getLogger(__name__)


def build_report_email(
    *,
    report_text: str,
    run_date: str,
    new_items_count: int,
    report_path: Path | None,
    settings: Settings,
) -> EmailMessage:
    """
    Build an EmailMessage from the report text.

    - If settings.smtp_attachment is True and report_path is given, the
      .txt is attached as a file (multipart/mixed). The body is a short
      cover message with new_items_count and run_date.
    - If smtp_attachment is False, the full report text is the body
      (text/plain only, no attachment).

    Returns the EmailMessage, ready to hand to smtp.send_email().
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
        # Short cover + full report attached
        cover = _build_cover(run_date, new_items_count, report_path)
        msg.set_content(cover, subtype="plain", charset="utf-8")
        msg.add_attachment(
            report_text.encode("utf-8"),
            maintype="text",
            subtype="plain",
            filename=report_path.name,
        )
        logger.info(
            "Built email with attachment: %s (%d bytes)",
            report_path.name, len(report_text),
        )
    else:
        # Full report in the body
        msg.set_content(report_text, subtype="plain", charset="utf-8")
        logger.info(
            "Built email with full report in body (%d bytes)", len(report_text),
        )

    return msg


def _build_cover(run_date: str, new_items_count: int, report_path: Path) -> str:
    """The short text the recipient sees before opening the attachment."""
    return (
        f"Céges Gépjármű Havi Riport — {run_date}\n"
        f"\n"
        f"Ebben a hónapban {new_items_count} új, a céges gépjárműveket "
        f"érintő jogszabályváltozás jelent meg a Magyar Közlönyben.\n"
        f"\n"
        f"Részletek a mellékelt fájlban: {report_path.name}\n"
        f"\n"
        f"--\n"
        f"Automatikusan generálva · gpjarmu-riport\n"
    )


__all__ = ["build_report_email"]
