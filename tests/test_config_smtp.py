"""Tests for the Settings SMTP validation (freemail.hu specifics)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from gpjarmu_riport.config import LLMProvider, Settings


# The user's .env file may set SMTP_HOST to something other than the default
# we want to test. This fixture points BaseSettings at an empty env file
# so the Field(default=...) values are the source of truth.
@pytest.fixture(autouse=True)
def _isolated_settings_env(tmp_path, monkeypatch):
    fake_env = tmp_path / ".env"
    fake_env.write_text("", encoding="utf-8")
    from gpjarmu_riport.config import Settings
    original_env_file = Settings.model_config.get("env_file")
    Settings.model_config["env_file"] = str(fake_env)
    for k in (
        "SMTP_ENABLED", "SMTP_HOST", "SMTP_PORT", "SMTP_SECURITY",
        "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_TIMEOUT", "SMTP_ATTACHMENT",
        "EMAIL_FROM", "EMAIL_TO", "EMAIL_SUBJECT_PREFIX",
    ):
        monkeypatch.delenv(k, raising=False)
    # Clear the cached settings so the new env_file is picked up
    from gpjarmu_riport import config
    config._cached_settings = None
    yield
    Settings.model_config["env_file"] = original_env_file
    config._cached_settings = None


def _base(**overrides) -> Settings:
    defaults = dict(
        llm_provider=LLMProvider.OPENAI,
        llm_api_key="test-key",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_default_smtp_is_freemail_starttls() -> None:
    s = _base()
    assert s.smtp_host == "smtp.freemail.hu"
    assert s.smtp_port == 587
    assert s.smtp_security == "starttls"
    assert s.smtp_attachment is True
    assert s.smtp_enabled is False  # off by default


def test_smtp_security_validates_value() -> None:
    with pytest.raises(ValidationError, match="smtp_security"):
        Settings(
            llm_provider=LLMProvider.OPENAI,
            llm_api_key="test",
            smtp_security="banana",
        )


def test_smtp_security_is_case_insensitive() -> None:
    s = _base(smtp_security="STARTTLS")
    assert s.smtp_security == "starttls"
    s2 = _base(smtp_security="  Ssl  ")
    assert s2.smtp_security == "ssl"


def test_validate_for_run_rejects_empty_username_when_enabled() -> None:
    s = _base(
        smtp_enabled=True,
        smtp_host="smtp.freemail.hu",
        smtp_port=587,
        smtp_security="starttls",
        smtp_username="",
        smtp_password="secret",
    )
    with pytest.raises(ValueError, match="SMTP_USERNAME is empty.*freemail"):
        s.validate_for_run()


def test_validate_for_run_rejects_empty_password_when_enabled() -> None:
    s = _base(
        smtp_enabled=True,
        smtp_host="smtp.freemail.hu",
        smtp_port=587,
        smtp_security="starttls",
        smtp_username="ger@freemail.hu",
        smtp_password="",
    )
    with pytest.raises(ValueError, match="SMTP_PASSWORD is empty.*freemail"):
        s.validate_for_run()


def test_validate_for_run_rejects_wrong_freemail_port() -> None:
    s = _base(
        smtp_enabled=True,
        smtp_host="smtp.freemail.hu",
        smtp_port=25,  # not supported by freemail
        smtp_security="starttls",
        smtp_username="ger@freemail.hu",
        smtp_password="secret",
    )
    with pytest.raises(ValueError, match="freemail.hu does not accept.*25"):
        s.validate_for_run()


def test_validate_for_run_accepts_freemail_default_port() -> None:
    s = _base(
        smtp_enabled=True,
        smtp_host="smtp.freemail.hu",
        smtp_port=587,
        smtp_security="starttls",
        smtp_username="ger@freemail.hu",
        smtp_password="secret",
    )
    # Should not raise
    s.validate_for_run()


def test_validate_for_run_accepts_freemail_ssl_port() -> None:
    s = _base(
        smtp_enabled=True,
        smtp_host="smtp.freemail.hu",
        smtp_port=465,
        smtp_security="ssl",
        smtp_username="ger@freemail.hu",
        smtp_password="secret",
    )
    # Should not raise
    s.validate_for_run()


def test_validate_for_run_does_not_check_port_for_other_hosts() -> None:
    # A custom SMTP server on port 25 should NOT trigger the freemail guard
    s = _base(
        smtp_enabled=True,
        smtp_host="mail.mycompany.hu",
        smtp_port=25,
        smtp_security="starttls",
        smtp_username="ger",
        smtp_password="secret",
    )
    s.validate_for_run()  # should not raise
