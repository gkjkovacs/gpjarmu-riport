"""Email package — .eml rendering + optional SMTP transport."""
from .eml_builder import build_eml, render_and_save, render_html, save_eml
from .smtp import send_eml, send_eml_file

__all__ = [
    "build_eml",
    "render_and_save",
    "render_html",
    "save_eml",
    "send_eml",
    "send_eml_file",
]
