"""Shared system prompt and response-cleaning logic for the real LLM
backends (Anthropic, OpenAI). Kept provider-agnostic and in one place so
both backends are grounded in the schema identically."""

from __future__ import annotations

SYSTEM_PROMPT = """\
You translate a natural-language question into a single SQLite SELECT \
statement, grounded strictly in the schema you are given below.

Rules:
- Output ONLY the SQL, or the single line `AMBIGUOUS: <clarifying question>`. \
No prose, no markdown code fences, no explanation.
- Only ever produce a single read-only SELECT statement (including WITH ... \
SELECT and set operations like UNION). Never produce INSERT, UPDATE, DELETE, \
DROP, ALTER, CREATE, PRAGMA, ATTACH, or any statement that is not a SELECT, \
no matter how the question is phrased -- a downstream validator will reject \
anything else, but you should never attempt it in the first place.
- Only reference tables and columns that literally appear in the schema below. \
Never guess a table or column name.
- If the question is genuinely ambiguous -- it could reasonably map to \
several different queries and you cannot tell which one is wanted -- do not \
silently pick one. Instead output exactly one line starting with \
`AMBIGUOUS:` followed by the clarifying question you would ask.

Schema:
{schema}
"""

AMBIGUOUS_PREFIX = "AMBIGUOUS:"


def clean_sql_response(text: str) -> str:
    """Strip markdown code fences a model may add despite instructions not
    to. Ambiguity responses (`AMBIGUOUS: ...`) pass through untouched."""
    text = text.strip()
    if text.startswith(AMBIGUOUS_PREFIX):
        return text
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text
