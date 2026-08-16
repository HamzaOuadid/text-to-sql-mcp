"""LLM provider abstraction.

`LLMClient` is a small Protocol so the rest of the app (service.py,
mcp_server.py, the eval runner) never depends on a specific provider SDK.
Three implementations exist:

- `AnthropicLLMClient` -- calls the real Anthropic API (used when
  `ANTHROPIC_API_KEY` is configured).
- `OpenAILLMClient` -- calls the real OpenAI API (used when
  `OPENAI_API_KEY` is configured and no Anthropic key is present).
- `RuleBasedLLMClient` -- a deterministic, fixture-driven translator for a
  fixed set of known question patterns. No network, no API key, always
  available. This is what the test suite and the offline demo run
  against; see the README for exactly what it can and can't answer.

`llm/factory.py` picks one of these based on configuration. The AST
validator downstream treats their output identically -- it has no idea,
and does not care, which one produced a given SQL string.
"""

from __future__ import annotations

from typing import Protocol

from ..validator.models import Schema


class LLMGenerationError(RuntimeError):
    """Raised when an LLMClient cannot produce a SQL candidate for a
    question (unknown question pattern, API error, etc.)."""


class LLMClient(Protocol):
    """Minimal interface every NL->SQL backend implements."""

    name: str

    def generate_sql(self, question: str, schema: Schema) -> str:
        """Return a single candidate SQL string for `question`, grounded
        in `schema`. Raises `LLMGenerationError` if no SQL could be
        produced. The returned string is *never* trusted -- it always
        passes through `validate_sql` before anything executes it."""
        ...
