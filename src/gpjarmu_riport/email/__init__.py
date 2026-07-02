"""Email package — text report rendering + (optional) SMTP transport.

The main render path produces a .txt report. The HTML body and SMTP
transport are kept as a future option (render_html, smtp.send_eml_file)
but no longer wired into the pipeline by default.
"""
from .eml_builder import (
    _build_text_body,
    _html_to_text,
    build_text_report,
    render_and_save_report,
    render_html,
    save_text_report,
)
from .smtp import send_eml_file  # noqa: F401  (kept for future re-enablement)

__all__ = [
    "build_text_report",
    "save_text_report",
    "render_and_save_report",
    "render_html",
    "send_eml_file",
]
