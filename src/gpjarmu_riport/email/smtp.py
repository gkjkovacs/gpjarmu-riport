"""
SMTP transport for sending the .txt report by email.

This is the low-level transport: connect to the SMTP server, optionally
upgrade to TLS, authenticate, send the message. It does not know about
the report or the message body — that lives in mailer.py.

Supports three connection modes (selected via settings.smtp_security):
  - "starttls"  (default; port 587) — STARTTLS upgrade, recommended
  - "ssl"       (port 465)           — implicit TLS from the start
  - "none"      (port 25, NOT recommended for production)

Default target is freemail.hu:587 (the most common Hungarian freemail
provider), but the host/port/security are all configurable, so this
works with any standard SMTP server (Gmail, Outlook, custom, etc.)
as long as the user supplies the right credentials.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from ..config import Settings

logger = logging.getLogger(__name__)


def send_email(msg: EmailMessage, settings: Settings) -> None:
    """
    Send the EmailMessage via SMTP, using the connection mode from settings.

    Raises:
        RuntimeError: if SMTP is not enabled in settings.
        smtplib.SMTPAuthenticationError: bad username/password.
        smtplib.SMTPException: any other SMTP-level failure.
        OSError: connection-level failure (DNS, refused, timeout).
    """
    if not settings.smtp_enabled:
        raise RuntimeError(
            "SMTP is not enabled. Set SMTP_ENABLED=true in .env first."
        )

    security = settings.smtp_security
    logger.info(
        "Connecting to SMTP %s:%d (security=%s, user=%s)",
        settings.smtp_host, settings.smtp_port, security, settings.smtp_username,
    )

    if security == "ssl":
        _send_via_ssl(msg, settings)
    elif security == "starttls":
        _send_via_starttls(msg, settings)
    elif security == "none":
        _send_via_plain(msg, settings)
    else:
        # Validated by Settings, but defensive programming: never silently send.
        raise RuntimeError(f"Unknown smtp_security: {security!r}")

    logger.info(
        "Sent email: from=%s, to=%s, subject=%s",
        settings.email_from, settings.email_to, msg["Subject"],
    )


def _send_via_ssl(msg: EmailMessage, settings: Settings) -> None:
    """Implicit TLS (port 465). The connection is encrypted from byte 0."""
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(
        settings.smtp_host, settings.smtp_port,
        context=context, timeout=settings.smtp_timeout,
    ) as server:
        server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg)


def _send_via_starttls(msg: EmailMessage, settings: Settings) -> None:
    """STARTTLS upgrade (port 587). Plain text handshake, then TLS upgrade."""
    context = ssl.create_default_context()
    with smtplib.SMTP(
        settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout,
    ) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()  # re-identify over the encrypted channel
        server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg)


def _send_via_plain(msg: EmailMessage, settings: Settings) -> None:
    """Plain SMTP, no encryption. NOT recommended; only for local debug servers."""
    logger.warning(
        "Sending email in plain text (no TLS). Credentials and content are "
        "visible on the network. Set smtp_security='starttls' or 'ssl' for production."
    )
    with smtplib.SMTP(
        settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout,
    ) as server:
        server.ehlo()
        server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg)


__all__ = ["send_email"]
