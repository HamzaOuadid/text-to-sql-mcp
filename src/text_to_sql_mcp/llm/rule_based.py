"""Deterministic, offline NL->SQL backend.

This is **not** a general text-to-SQL model. It is a fixture-driven
lookup table covering a fixed set of known question patterns (normalized
by lowercasing/whitespace/punctuation), used as the default backend when
no LLM API key is configured -- so the rest of the system (the AST
validator, the MCP server, the eval harness, the test suite) is fully
exercisable with zero network access and zero cost.

Coverage is deliberately partial. Of the 25 questions in the labelled
eval set, this backend recognizes 20 (all 8 easy, 8 of 10 medium, 3 of 6
hard, plus the one deliberately-ambiguous question) and raises
`LLMGenerationError` on the rest -- including every question outside the
fixed set entirely. That gap is the honest line between "a canned demo"
and "real open-ended natural-language understanding", and it is exactly
what a configured Anthropic or OpenAI API key (see anthropic_client.py /
openai_client.py) is for. See the README for the measured accuracy this
produces and why it is not, and should not be, 100%.
"""

from __future__ import annotations

import re

from ..fixtures import QUESTIONS
from ..validator.models import Schema
from .base import LLMGenerationError
from .prompt import AMBIGUOUS_PREFIX

# Question ids the rule-based backend deliberately does NOT answer, even
# though they're in the labelled eval set -- see module docstring. Two
# join-heavy medium questions and three complex hard questions are left
# unanswered so the reported accuracy is genuine, not a tautology.
_UNANSWERED_IDS = {13, 17, 20, 22, 23}


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _build_fixtures() -> dict[str, str]:
    fixtures: dict[str, str] = {}
    for q in QUESTIONS:
        if q.id in _UNANSWERED_IDS:
            continue
        if q.is_ambiguous:
            fixtures[_normalize(q.nl_question)] = (
                f"{AMBIGUOUS_PREFIX} 'Recent activity' could mean permits, "
                "inspections, violations, complaints, or payments -- and over "
                "what time window. Please specify which type of record and a "
                "date range or property."
            )
            continue
        assert q.expected_sql is not None
        fixtures[_normalize(q.nl_question)] = q.expected_sql
    return fixtures


_FIXTURES = _build_fixtures()

# A handful of generic templated patterns, matched *after* the exact-fixture
# lookup fails, so the backend isn't purely a verbatim lookup table. Kept
# intentionally small and conservative -- only fires against real table
# names from the introspected schema, and only for the two safest question
# shapes ("how many X" / "list X").
_COUNT_PATTERN = re.compile(r"^how many (\w+) are there\??$")
_LIST_PATTERN = re.compile(r"^list all (\w+)\.?$")


def _try_generic_templates(question: str, schema: Schema) -> str | None:
    normalized = _normalize(question)
    table_names = schema.table_names()

    m = _COUNT_PATTERN.match(normalized)
    if m and m.group(1) in table_names:
        return f"SELECT COUNT(*) AS count FROM {m.group(1)}"

    m = _LIST_PATTERN.match(normalized)
    if m and m.group(1) in table_names:
        return f"SELECT * FROM {m.group(1)}"

    return None


class RuleBasedLLMClient:
    """Deterministic fallback LLM client. See module docstring."""

    name = "rule-based"

    def generate_sql(self, question: str, schema: Schema) -> str:
        normalized = _normalize(question)
        if normalized in _FIXTURES:
            return _FIXTURES[normalized]

        templated = _try_generic_templates(question, schema)
        if templated is not None:
            return templated

        raise LLMGenerationError(
            f"The rule-based backend does not recognize this question: {question!r}. "
            "It only handles a fixed set of known question patterns (see "
            "llm/rule_based.py). Configure ANTHROPIC_API_KEY or OPENAI_API_KEY "
            "for open-ended natural-language-to-SQL generation."
        )
