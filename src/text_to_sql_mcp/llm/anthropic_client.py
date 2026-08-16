"""Real NL->SQL generation via the Anthropic API.

Used automatically when `ANTHROPIC_API_KEY` is set (see llm/factory.py).
This is the "true" open-ended text-to-SQL path -- unlike the rule-based
fallback, it can handle arbitrary phrasings, not just a fixed fixture
set. Its output is treated with exactly as much suspicion as any other
backend's: every candidate SQL string still goes through `validate_sql`
before anything executes it.
"""

from __future__ import annotations

from ..introspection import format_schema_for_prompt
from ..validator.models import Schema
from .base import LLMGenerationError
from .prompt import SYSTEM_PROMPT, clean_sql_response


class AnthropicLLMClient:
    name = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-opus-5") -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - dependency always installed in this env
            raise LLMGenerationError(
                "The 'anthropic' package is not installed. Install it with "
                "`pip install anthropic` or `pip install -e '.[anthropic]'`."
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def generate_sql(self, question: str, schema: Schema) -> str:
        system = SYSTEM_PROMPT.format(schema=format_schema_for_prompt(schema))
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": question}],
            )
        except Exception as exc:  # anthropic.APIError and friends
            raise LLMGenerationError(f"Anthropic API call failed: {exc}") from exc

        if response.stop_reason == "refusal":
            raise LLMGenerationError("Anthropic declined to answer this question (safety refusal).")

        text_parts = [block.text for block in response.content if block.type == "text"]
        text = "".join(text_parts).strip()
        if not text:
            raise LLMGenerationError("Anthropic returned an empty response.")
        return clean_sql_response(text)
