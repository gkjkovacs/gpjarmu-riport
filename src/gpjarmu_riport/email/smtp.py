"""
Optional SMTP transport.

Sends the .eml to the configured SMTP server. Only used when
settings.smtp_enabled is True.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from ..config import Settings

logger = logging.getLogger(__name__)


def send_eml(msg: EmailMessage, settings: Settings) -> None:
    """Send the EmailMessage via SMTP (STARTTLS on port 587 by default)."""
    if not settings.smtp_enabled:
        raise RuntimeError("SMTP is not enabled. Set SMTP_ENABLED=true in .env first.")

    context = ssl.create_default_context()
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=60) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg)
    logger.info(
        "Sent email: from=%s, to=%s, subject=%s",
        settings.email_from,
        settings.email_to,
        msg["Subject"],
    )


def send_eml_file(path: Path, settings: Settings) -> None:
    """Load a .eml file from disk and send it."""
    import email
    raw = path.read_bytes()
    msg = email.message_from_bytes(raw)
    send_eml(msg, settings)


__all__ = ["send_eml", "send_eml_file"]
