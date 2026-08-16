"""Real NL->SQL generation via the OpenAI API.

Used automatically when `OPENAI_API_KEY` is set and `ANTHROPIC_API_KEY` is
not (see llm/factory.py). Same contract and same system prompt shape as
the Anthropic backend -- its output is never trusted any more than any
other backend's; everything still passes through `validate_sql`.
"""

from __future__ import annotations

from ..introspection import format_schema_for_prompt
from ..validator.models import Schema
from .base import LLMGenerationError
from .prompt import SYSTEM_PROMPT, clean_sql_response


class OpenAILLMClient:
    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        try:
            import openai
        except ImportError as exc:  # pragma: no cover - dependency always installed in this env
            raise LLMGenerationError(
                "The 'openai' package is not installed. Install it with "
                "`pip install openai` or `pip install -e '.[openai]'`."
            ) from exc
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model

    def generate_sql(self, question: str, schema: Schema) -> str:
        system = SYSTEM_PROMPT.format(schema=format_schema_for_prompt(schema))
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": question},
                ],
            )
        except Exception as exc:  # openai.OpenAIError and friends
            raise LLMGenerationError(f"OpenAI API call failed: {exc}") from exc

        choice = response.choices[0] if response.choices else None
        text = (choice.message.content or "").strip() if choice else ""
        if not text:
            raise LLMGenerationError("OpenAI returned an empty response.")
        return clean_sql_response(text)
