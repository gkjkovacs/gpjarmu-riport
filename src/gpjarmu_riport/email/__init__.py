"""Email package — text report rendering + (optional) SMTP transport.

Main render path produces a .txt report. The SMTP transport is opt-in
(settings.smtp_enabled=true) and ships the report via the configured
SMTP server (default: freemail.hu:587 with STARTTLS).
"""
from .eml_builder import (
    _build_text_body,
    _html_to_text,
    build_text_report,
    render_and_save_report,
    render_html,
    save_text_report,
)
from .mailer import build_report_email
from .smtp import send_email  # noqa: F401  (public API)

__all__ = [
    "build_text_report",
    "save_text_report",
    "render_and_save_report",
    "render_html",
    "build_report_email",
    "send_email",
]
