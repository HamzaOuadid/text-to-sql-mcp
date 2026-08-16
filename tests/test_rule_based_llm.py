"""Tests for the deterministic rule-based NL->SQL backend used when no
LLM API key is configured."""

from __future__ import annotations

import pytest

from text_to_sql_mcp.fixtures import QUESTIONS
from text_to_sql_mcp.llm.base import LLMGenerationError
from text_to_sql_mcp.llm.prompt import AMBIGUOUS_PREFIX
from text_to_sql_mcp.llm.rule_based import RuleBasedLLMClient, _UNANSWERED_IDS


def test_answers_known_easy_question(schema) -> None:
    client = RuleBasedLLMClient()
    sql = client.generate_sql("How many permits are there in total?", schema)
    assert sql.strip().upper().startswith("SELECT")
    assert "permits" in sql.lower()


def test_is_case_and_punctuation_insensitive(schema) -> None:
    client = RuleBasedLLMClient()
    a = client.generate_sql("How many permits are there in total?", schema)
    b = client.generate_sql("  HOW MANY permits are there in total  ", schema)
    assert a == b


def test_handles_the_ambiguous_question(schema) -> None:
    client = RuleBasedLLMClient()
    response = client.generate_sql("Show me the recent activity.", schema)
    assert response.startswith(AMBIGUOUS_PREFIX)


def test_unknown_question_raises(schema) -> None:
    client = RuleBasedLLMClient()
    with pytest.raises(LLMGenerationError):
        client.generate_sql("What is the meaning of life?", schema)


def test_deliberately_unanswered_questions_raise(schema) -> None:
    """These are in the labelled eval set but intentionally NOT covered by
    the rule-based fixture set, so the reported eval accuracy is genuine
    rather than tautological -- see llm/rule_based.py."""
    client = RuleBasedLLMClient()
    unanswered = [q for q in QUESTIONS if q.id in _UNANSWERED_IDS]
    assert len(unanswered) == len(_UNANSWERED_IDS)
    for q in unanswered:
        with pytest.raises(LLMGenerationError):
            client.generate_sql(q.nl_question, schema)


def test_all_non_deliberately_unanswered_questions_are_covered(schema) -> None:
    client = RuleBasedLLMClient()
    for q in QUESTIONS:
        if q.id in _UNANSWERED_IDS:
            continue
        # Must not raise.
        result = client.generate_sql(q.nl_question, schema)
        assert isinstance(result, str) and result.strip()


def test_generic_count_template(schema) -> None:
    client = RuleBasedLLMClient()
    sql = client.generate_sql("How many employees are there?", schema)
    assert sql.strip().lower() == "select count(*) as count from employees"


def test_generic_list_template(schema) -> None:
    client = RuleBasedLLMClient()
    sql = client.generate_sql("List all zones.", schema)
    assert sql.strip().lower() == "select * from zones"
