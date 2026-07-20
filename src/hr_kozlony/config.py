"""
Centralized configuration loaded from .env via Pydantic Settings.

The same Settings object is passed into the LangGraph nodes, so any config
change (e.g. a different LLM model or a stricter relevance threshold) requires
only a .env edit and a restart.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    """Supported LLM providers (factory pattern)."""

    OPENAI = "openai"          # any OpenAI-compatible endpoint (Ollama Cloud, OpenAI, etc.)
    ANTHROPIC = "anthropic"    # Claude (requires langchain-anthropic)
    OLLAMA = "ollama"          # local Ollama (requires langchain-ollama)


class Settings(BaseSettings):
    """Application settings, loaded from .env and environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- LLM ----
    llm_provider: LLMProvider = Field(
        default=LLMProvider.OPENAI,
        description="LLM provider. OPENAI works for any OpenAI-compatible endpoint.",
    )
    llm_base_url: str = Field(
        default="https://ollama.com/v1",
        description="Base URL for the OpenAI-compatible API.",
    )
    llm_api_key: str = Field(
        default="",
        description="API key for the LLM provider.",
    )
    llm_model: str = Field(
        default="minimax-m3:cloud",
        description="Model name. For Ollama Cloud use ':cloud' suffix.",
    )
    llm_temperature_classify: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_temperature_expand: float = Field(default=0.2, ge=0.0, le=2.0)
    llm_max_tokens_classify: int = Field(default=512, ge=64, le=32000)
    llm_max_tokens_expand: int = Field(default=1024, ge=64, le=32000)
    llm_timeout: int = Field(default=120, ge=10, le=600)

    # ---- Monitor ----
    lookback_days: int = Field(default=30, ge=1, le=365)
    relevance_threshold: float = Field(default=0.50, ge=0.0, le=1.0)
    kozlony_base_url: str = Field(default="https://magyarkozlony.hu")
    max_issues_per_run: int = Field(default=50, ge=1, le=500)
    min_bekezdes_length: int = Field(default=30, ge=10, le=1000)
    scraper_timeout: int = Field(default=30, ge=5, le=300)
    scraper_user_agent: str = Field(
        default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) GpjarmuRiport/1.0"
    )
    # --- Performance: classify node ---
    classify_concurrency: int = Field(
        default=5, ge=1, le=32,
        description="Max parallel LLM calls in the classify node.",
    )
    keyword_filter_enabled: bool = Field(
        default=True,
        description=(
            "If true, skip bekezdések that contain no vehicle-related keyword "
            "before calling the LLM. Cuts 80-95% of API calls."
        ),
    )

    # ---- State ----
    state_db_path: Path = Field(default=Path("./data/state.db"))

    # ---- Output ----
    output_dir: Path = Field(default=Path("./output"))
    email_from: str = Field(default="hr-kozlony@localhost")
    email_to: str = Field(default="you@example.com")
    email_subject_prefix: str = Field(default="[HR riport]")

    # ---- SMTP (optional) ----
    smtp_enabled: bool = Field(default=False)
    smtp_host: str = Field(
        default="smtp.freemail.hu",
        description="SMTP server hostname. Default: freemail.hu (port 587 + STARTTLS).",
    )
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_security: str = Field(
        default="starttls",
        description=(
            "Connection security. One of: "
            "'starttls' (recommended, port 587), "
            "'ssl' (implicit TLS, port 465), "
            "'none' (plain, NOT recommended)."
        ),
    )
    smtp_username: str = Field(
        default="",
        description=(
            "SMTP username — for freemail.hu this is your FULL email address "
            "(e.g. gergely.kovacs@freemail.hu), not just the local part."
        ),
    )
    smtp_password: str = Field(
        default="",
        description=(
            "SMTP password — the same password you use to log in at "
            "https://accounts.freemail.hu (NOT the same as the webmail token)."
        ),
    )
    smtp_timeout: int = Field(default=60, ge=5, le=600)
    smtp_attachment: bool = Field(
        default=True,
        description=(
            "If true, the .txt report is attached to the email as a file. "
            "If false, the report body is the email body itself (plain text)."
        ),
    )
    smtp_html_attachment: bool = Field(
        default=True,
        description=(
            "If true (and smtp_attachment is also true), the HTML version of "
            "the report is generated on-the-fly and attached as a second file. "
            "Recipients get both .txt and .html in the same email; Outlook, "
            "Gmail, and Apple Mail render the .html with clickable links and "
            "badges, while any text-only client can fall back to the .txt."
        ),
    )

    # ---- Logging ----
    log_level: str = Field(default="INFO")
    log_file: Optional[Path] = Field(default=None)

    # ---- Dev / debug ----
    dry_run: bool = Field(default=False)
    llm_debug: bool = Field(default=False)

    @field_validator("state_db_path", "output_dir", mode="before")
    @classmethod
    def _expand_path(cls, v: str | Path) -> Path:
        p = Path(v).expanduser()
        return p.resolve() if p.is_absolute() else (Path.cwd() / p).resolve()

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        v = v.upper()
        if v not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            raise ValueError(f"Invalid log level: {v}")
        return v

    @field_validator("smtp_security")
    @classmethod
    def _validate_smtp_security(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in ("starttls", "ssl", "none"):
            raise ValueError(
                f"Invalid smtp_security: {v!r}. Must be 'starttls', 'ssl', or 'none'."
            )
        return v

    def ensure_dirs(self) -> None:
        """Create output and data dirs if missing."""
        self.state_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def validate_for_run(self) -> None:
        """Check critical fields are populated. Called by CLI before invoking the graph."""
        if not self.llm_api_key:
            raise ValueError(
                "LLM_API_KEY is empty. Set it in .env — get your key at "
                "https://ollama.com/settings (or your provider's dashboard)."
            )
        if self.smtp_enabled:
            if not self.smtp_username:
                raise ValueError(
                    "SMTP_ENABLED=true but SMTP_USERNAME is empty. "
                    "For freemail.hu this must be your full email address "
                    "(e.g. gergely.kovacs@freemail.hu), not just the local part."
                )
            if not self.smtp_password:
                raise ValueError(
                    "SMTP_ENABLED=true but SMTP_PASSWORD is empty. "
                    "Use the same password you log in with at "
                    "https://accounts.freemail.hu."
                )
            # freemail.hu port guidance
            if "freemail.hu" in self.smtp_host.lower() and self.smtp_port not in (465, 587):
                raise ValueError(
                    f"freemail.hu does not accept SMTP connections on port {self.smtp_port}. "
                    f"Use port 587 (STARTTLS, default) or 465 (SSL)."
                )


_cached_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a memoized Settings instance."""
    global _cached_settings
    if _cached_settings is None:
        _cached_settings = Settings()
        _cached_settings.ensure_dirs()
    return _cached_settings


def reload_settings() -> Settings:
    """Drop the cached settings and reload from .env (useful in tests)."""
    global _cached_settings
    _cached_settings = None
    return get_settings()


__all__ = ["LLMProvider", "Settings", "get_settings", "reload_settings"]
