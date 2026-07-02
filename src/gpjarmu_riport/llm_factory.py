"""
LLM factory: returns a LangChain ChatModel for the configured provider.

Currently supported:
- OPENAI: any OpenAI-compatible endpoint (Ollama Cloud, OpenAI, LM Studio, etc.)
- ANTHROPIC: Claude (requires `pip install langchain-anthropic`)
- OLLAMA: local Ollama (requires `pip install langchain-ollama`)

The classifier and expander nodes use this factory with different temperature
and max_tokens settings, but the same model.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

from langchain_core.language_models import BaseChatModel

from .config import LLMProvider, Settings, get_settings

logger = logging.getLogger(__name__)


def build_chat_model(
    settings: Settings | None = None,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    role: Literal["classify", "expand"] | None = None,
) -> BaseChatModel:
    """
    Build a LangChain ChatModel for the configured provider.

    If `role` is given, the model's temperature/max_tokens are taken from
    the role-specific config (llm_temperature_classify / llm_max_tokens_classify
    or llm_temperature_expand / llm_max_tokens_expand). Explicit
    temperature / max_tokens parameters override role defaults.
    """
    s = settings or get_settings()

    if role == "classify":
        temperature = temperature if temperature is not None else s.llm_temperature_classify
        max_tokens = max_tokens if max_tokens is not None else s.llm_max_tokens_classify
    elif role == "expand":
        temperature = temperature if temperature is not None else s.llm_temperature_expand
        max_tokens = max_tokens if max_tokens is not None else s.llm_max_tokens_expand

    common: dict = {
        "temperature": temperature if temperature is not None else 0.0,
        "max_tokens": max_tokens if max_tokens is not None else 1024,
        "timeout": s.llm_timeout,
    }

    if s.llm_provider == LLMProvider.OPENAI:
        # This works for any OpenAI-compatible endpoint, not just OpenAI.
        from langchain_openai import ChatOpenAI
        logger.debug(
            "Building ChatOpenAI: base_url=%s, model=%s, temperature=%s, max_tokens=%s",
            s.llm_base_url, s.llm_model, common["temperature"], common["max_tokens"],
        )
        return ChatOpenAI(
            model=s.llm_model,
            base_url=s.llm_base_url,
            api_key=s.llm_api_key,
            **common,
        )

    if s.llm_provider == LLMProvider.ANTHROPIC:
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as e:
            raise ImportError(
                "Anthropic provider requires `pip install langchain-anthropic`."
            ) from e
        logger.debug("Building ChatAnthropic: model=%s", s.llm_model)
        return ChatAnthropic(
            model=s.llm_model,
            api_key=s.llm_api_key,
            **common,
        )

    if s.llm_provider == LLMProvider.OLLAMA:
        try:
            from langchain_ollama import ChatOllama
        except ImportError as e:
            raise ImportError(
                "Ollama provider requires `pip install langchain-ollama`."
            ) from e
        logger.debug("Building ChatOllama: base_url=%s, model=%s", s.llm_base_url, s.llm_model)
        return ChatOllama(
            model=s.llm_model,
            base_url=s.llm_base_url,
            **common,
        )

    raise ValueError(f"Unknown LLM provider: {s.llm_provider}")


@lru_cache(maxsize=1)
def _cached_classifier(settings_id: int) -> BaseChatModel:
    return build_chat_model(role="classify")


@lru_cache(maxsize=1)
def _cached_expander(settings_id: int) -> BaseChatModel:
    return build_chat_model(role="expand")


def get_classifier() -> BaseChatModel:
    """Return the LLM used for relevance classification. Cached per settings instance."""
    s = get_settings()
    return _cached_classifier(id(s))


def get_expander() -> BaseChatModel:
    """Return the LLM used for summary expansion. Cached per settings instance."""
    s = get_settings()
    return _cached_expander(id(s))


def clear_cache() -> None:
    """Drop cached models (e.g. after a config change in tests)."""
    _cached_classifier.cache_clear()
    _cached_expander.cache_clear()


__all__ = ["build_chat_model", "get_classifier", "get_expander", "clear_cache"]
