"""End-to-end `service.ask()` tests: a natural-language question in,
correct SQL and a correct answer out (or an honest, non-silent refusal
when the backend genuinely can't answer)."""

from __future__ import annotations

from text_to_sql_mcp.llm.rule_based import RuleBasedLLMClient
from text_to_sql_mcp.service import ask
from text_to_sql_mcp.validator.models import RejectionReason


def test_ask_answers_a_known_question(settings) -> None:
    result = ask(
        "How many permits are there in total?",
        llm_client=RuleBasedLLMClient(),
        settings=settings,
    )
    assert result.rejected is False
    assert result.rows == [{"count": 2600}]
    assert result.llm_backend == "rule-based"


def test_ask_answers_a_join_heavy_known_question(settings) -> None:
    result = ask(
        "How many permits does each contractor hold?",
        llm_client=RuleBasedLLMClient(),
        settings=settings,
    )
    assert result.rejected is False
    assert len(result.rows) > 0
    assert "business_name" in result.rows[0]
    assert "permit_count" in result.rows[0]


def test_ask_handles_ambiguous_question_without_silently_guessing(settings) -> None:
    result = ask(
        "Show me the recent activity.",
        llm_client=RuleBasedLLMClient(),
        settings=settings,
    )
    assert result.rejected is True
    assert result.rejection_reason_code == "ambiguous_question"
    assert result.rows == []


def test_ask_surfaces_generation_failure_as_rejection_not_a_crash(settings) -> None:
    result = ask(
        "What is the meaning of life?",
        llm_client=RuleBasedLLMClient(),
        settings=settings,
    )
    assert result.rejected is True
    assert result.rejection_reason_code == RejectionReason.GENERATION_FAILED.value
