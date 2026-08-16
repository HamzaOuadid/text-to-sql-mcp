"""Picks an `LLMClient` implementation based on configuration.

Precedence: Anthropic (if `ANTHROPIC_API_KEY` set) -> OpenAI (if
`OPENAI_API_KEY` set) -> rule-based deterministic fallback (always
available, no configuration required). This is what makes the whole
system usable out of the box in this environment, where no LLM API keys
are configured -- see the README for exactly what that trade-off means
for the accuracy numbers.
"""

from __future__ import annotations

import logging

from ..config import Settings
from .base import LLMClient
from .rule_based import RuleBasedLLMClient

logger = logging.getLogger(__name__)


def get_llm_client(settings: Settings) -> LLMClient:
    if settings.anthropic_api_key:
        from .anthropic_client import AnthropicLLMClient

        logger.info("Using Anthropic LLM backend (model=%s)", settings.anthropic_model)
        return AnthropicLLMClient(
            api_key=settings.anthropic_api_key, model=settings.anthropic_model
        )
    if settings.openai_api_key:
        from .openai_client import OpenAILLMClient

        logger.info("Using OpenAI LLM backend (model=%s)", settings.openai_model)
        return OpenAILLMClient(api_key=settings.openai_api_key, model=settings.openai_model)

    logger.info("No LLM API key configured; using deterministic rule-based backend")
    return RuleBasedLLMClient()
