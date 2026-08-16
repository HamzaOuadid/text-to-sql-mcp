"""Eval-harness tests: accuracy measurement, difficulty/join-heaviness
breakdown, and the "not just claimed" acceptance criterion -- these
assert on the actual numbers produced by a real run against the rule-
based backend, not hand-waved."""

from __future__ import annotations

from text_to_sql_mcp.eval.runner import run_eval
from text_to_sql_mcp.fixtures import QUESTIONS
from text_to_sql_mcp.llm.rule_based import RuleBasedLLMClient


def test_eval_set_has_20_to_30_questions() -> None:
    assert 20 <= len(QUESTIONS) <= 30


def test_eval_set_spans_all_three_difficulties() -> None:
    difficulties = {q.difficulty for q in QUESTIONS}
    assert difficulties == {"easy", "medium", "hard"}


def test_eval_set_has_join_heavy_questions() -> None:
    assert any(q.is_join_heavy for q in QUESTIONS)
    assert any(not q.is_join_heavy for q in QUESTIONS)


def test_run_eval_produces_report_with_expected_shape(settings) -> None:
    report = run_eval(settings, RuleBasedLLMClient())
    d = report.as_dict()
    assert d["total_questions"] == len(QUESTIONS)
    assert 0.0 <= d["accuracy"] <= 1.0
    assert set(d["by_difficulty"].keys()) == {"easy", "medium", "hard"}
    assert set(d["by_join_heaviness"].keys()) == {"simple", "join_heavy"}


def test_rule_based_backend_gets_all_easy_questions_correct(settings) -> None:
    report = run_eval(settings, RuleBasedLLMClient())
    assert report.accuracy_by_difficulty()["easy"]["accuracy"] == 1.0


def test_rule_based_backend_accuracy_is_not_perfect(settings) -> None:
    """The eval harness must measure real behavior, not always report
    100% -- the rule-based backend deliberately leaves some questions
    unanswered (see llm/rule_based.py), so accuracy must reflect that."""
    report = run_eval(settings, RuleBasedLLMClient())
    assert 0.0 < report.accuracy < 1.0


def test_join_heavy_accuracy_is_lower_than_simple_accuracy(settings) -> None:
    """Join-heavy questions are genuinely harder for the rule-based
    backend -- this is the concrete instance of the edge case "track
    accuracy separately for join-heavy questions since they're harder"."""
    report = run_eval(settings, RuleBasedLLMClient())
    by_join = report.accuracy_by_join_heaviness()
    assert by_join["join_heavy"]["accuracy"] < by_join["simple"]["accuracy"]


def test_ambiguous_question_counts_correct_when_flagged_not_guessed(settings) -> None:
    report = run_eval(settings, RuleBasedLLMClient())
    ambiguous_results = [r for r in report.results if r.question.is_ambiguous]
    assert len(ambiguous_results) == 1
    assert ambiguous_results[0].correct is True
    assert ambiguous_results[0].rejected is True
