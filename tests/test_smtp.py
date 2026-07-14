"""Tests for the SMTP transport (smtp.py) and the report mailer (mailer.py).

Strategy: we don't actually talk to freemail.hu (or any real server).
We use smtplib's own testing hooks and a mock SMTP class to verify
that the right commands are issued in the right order.
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gpjarmu_riport.config import LLMProvider, Settings
from gpjarmu_riport.email.mailer import build_report_email
from gpjarmu_riport.email.smtp import send_email


# --- settings fixtures -----------------------------------------------------


def _smtp_settings(**overrides) -> Settings:
    defaults = dict(
        llm_provider=LLMProvider.OPENAI,
        llm_api_key="test-key",
        smtp_enabled=True,
        smtp_host="smtp.freemail.hu",
        smtp_port=587,
        smtp_security="starttls",
        smtp_username="ger@freemail.hu",
        smtp_password="secret",
        smtp_timeout=30,
        smtp_attachment=True,
        email_from="ger@freemail.hu",
        email_to="peter@example.com",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _mock_smtp_server() -> MagicMock:
    """Return a MagicMock that acts as a context manager returning itself.

    smtplib.SMTP is used as `with smtplib.SMTP(...) as server:`. The MagicMock
    default __enter__ returns a *new* MagicMock, not the one we created —
    so we wire __enter__.return_value = the same mock. This is the same
    pattern the smtplib test suite itself uses.
    """
    m = MagicMock()
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    return m


def _sample_msg() -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "Test"
    msg["From"] = "ger@freemail.hu"
    msg["To"] = "peter@example.com"
    msg.set_content("Hello body", subtype="plain", charset="utf-8")
    return msg


# --- send_email: not enabled guard -----------------------------------------


def test_send_email_raises_when_smtp_disabled() -> None:
    s = _smtp_settings(smtp_enabled=False)
    with pytest.raises(RuntimeError, match="SMTP is not enabled"):
        send_email(_sample_msg(), s)


def test_send_email_raises_on_unknown_security() -> None:
    # Bypass the validator by constructing a Settings, then mutating the
    # private attribute. Pydantic v2 forbids this normally, so we go through
    # model_construct() which skips validation.
    from pydantic import BaseModel
    raw = _smtp_settings().model_dump()
    raw["smtp_security"] = "weird"
    s = Settings.model_construct(**raw)
    with pytest.raises(RuntimeError, match="Unknown smtp_security"):
        send_email(_sample_msg(), s)


# --- send_email: STARTTLS path --------------------------------------------


def test_send_email_starttls_uses_smtp_class() -> None:
    s = _smtp_settings(smtp_security="starttls", smtp_port=587)
    server = _mock_smtp_server()
    with patch("gpjarmu_riport.email.smtp.smtplib.SMTP", return_value=server) as smtp_cls:
        send_email(_sample_msg(), s)
    # STARTTLS path uses smtplib.SMTP (not SMTP_SSL)
    smtp_cls.assert_called_once_with("smtp.freemail.hu", 587, timeout=30)
    server.ehlo.assert_called()
    server.starttls.assert_called_once()
    # ehlo is called twice: once before, once after STARTTLS upgrade
    assert server.ehlo.call_count == 2
    server.login.assert_called_once_with("ger@freemail.hu", "secret")
    server.send_message.assert_called_once()


# --- send_email: SSL path --------------------------------------------------


def test_send_email_ssl_uses_smtp_ssl_class() -> None:
    s = _smtp_settings(smtp_security="ssl", smtp_port=465)
    server = _mock_smtp_server()
    with patch("gpjarmu_riport.email.smtp.smtplib.SMTP_SSL", return_value=server) as smtp_cls:
        send_email(_sample_msg(), s)
    smtp_cls.assert_called_once()
    args, kwargs = smtp_cls.call_args
    assert args[0] == "smtp.freemail.hu"
    assert args[1] == 465
    assert "context" in kwargs
    assert isinstance(kwargs["context"], ssl.SSLContext)
    # No STARTTLS in SSL path (we use SMTP_SSL, which negotiates TLS at connect)
    server.starttls.assert_not_called()
    server.login.assert_called_once_with("ger@freemail.hu", "secret")
    server.send_message.assert_called_once()


# --- send_email: plain path (smoke, no TLS) --------------------------------


def test_send_email_plain_skips_starttls(caplog) -> None:
    s = _smtp_settings(smtp_security="none", smtp_port=25)
    server = _mock_smtp_server()
    with patch("gpjarmu_riport.email.smtp.smtplib.SMTP", return_value=server):
        send_email(_sample_msg(), s)
    server.starttls.assert_not_called()
    server.login.assert_called_once()


# --- send_email: error propagation -----------------------------------------


def test_send_email_propagates_smtp_auth_error() -> None:
    s = _smtp_settings()
    server = _mock_smtp_server()
    server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"auth failed")
    with patch("gpjarmu_riport.email.smtp.smtplib.SMTP", return_value=server):
        with pytest.raises(smtplib.SMTPAuthenticationError):
            send_email(_sample_msg(), s)


# --- mailer: build_report_email -------------------------------------------


def test_build_report_email_with_attachment(tmp_path: Path) -> None:
    s = _smtp_settings(smtp_attachment=True)
    report_path = tmp_path / "gpjarmu-2026-07-02.txt"
    msg = build_report_email(
        report_text="Full report text\n" * 50,
        run_date="2026-07-02",
        new_items_count=3,
        report_path=report_path,
        settings=s,
    )
    # Subject
    assert "[Céges Gépjármű riport]" in msg["Subject"]
    assert "3 új változás" in msg["Subject"]
    # Multipart (cover + attachment)
    assert msg.is_multipart()
    parts = list(msg.walk())
    ctypes = [p.get_content_type() for p in parts]
    assert "text/plain" in ctypes
    # Cover body is short and includes the date + count
    body = next(
        p.get_payload(decode=True).decode("utf-8")
        for p in parts
        if p.get_content_type() == "text/plain" and p.get_filename() is None
    )
    assert "2026-07-02" in body
    assert "3 új" in body
    # Attachment is the full report
    attached = next(
        p for p in parts if p.get_filename() == "gpjarmu-2026-07-02.txt"
    )
    assert b"Full report text" in attached.get_payload(decode=True)


def test_build_report_email_body_only(tmp_path: Path) -> None:
    s = _smtp_settings(smtp_attachment=False)
    report_path = tmp_path / "gpjarmu-2026-07-02.txt"
    msg = build_report_email(
        report_text="Just the body, no attachment.",
        run_date="2026-07-02",
        new_items_count=1,
        report_path=report_path,
        settings=s,
    )
    # Not multipart when there's no attachment
    assert not msg.is_multipart()
    payload = msg.get_payload(decode=True).decode("utf-8")
    assert "Just the body, no attachment." in payload


def test_build_report_email_handles_zero_items(tmp_path: Path) -> None:
    s = _smtp_settings()
    report_path = tmp_path / "gpjarmu-2026-07-02.txt"
    msg = build_report_email(
        report_text="(empty report)",
        run_date="2026-07-02",
        new_items_count=0,
        report_path=report_path,
        settings=s,
    )
    assert "0 új változás" in msg["Subject"]
