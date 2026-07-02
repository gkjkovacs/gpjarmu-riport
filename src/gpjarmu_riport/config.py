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

    # ---- State ----
    state_db_path: Path = Field(default=Path("./data/state.db"))

    # ---- Output ----
    output_dir: Path = Field(default=Path("./output"))
    email_from: str = Field(default="gpjarmu-riport@localhost")
    email_to: str = Field(default="you@example.com")
    email_subject_prefix: str = Field(default="[Céges Gépjármű riport]")

    # ---- SMTP ----
    smtp_enabled: bool = Field(default=False)
    smtp_host: str = Field(default="smtp.gmail.com")
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = Field(default="")
    smtp_password: str = Field(default="")

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
        if self.smtp_enabled and not self.smtp_username:
            raise ValueError("SMTP_ENABLED=true but SMTP_USERNAME is empty.")
        if self.smtp_enabled and not self.smtp_password:
            raise ValueError("SMTP_ENABLED=true but SMTP_PASSWORD is empty.")


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
