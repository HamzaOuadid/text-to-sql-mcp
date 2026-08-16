"""query_log persistence and the operator-facing rejection-rate report.

Spec user story: "As an operator, I can see how often the validator is
actually catching something" -- the rejection rate must be reported
separately from accuracy (that's covered in test_eval_runner.py)."""

from __future__ import annotations

from pathlib import Path

from text_to_sql_mcp.query_log import log_query, rejection_rate_report
from text_to_sql_mcp.validator.models import RejectionReason


def test_empty_log_reports_zero(app_db_path: Path) -> None:
    report = rejection_rate_report(app_db_path)
    assert report.total == 0
    assert report.rejection_rate == 0.0


def test_logs_accepted_and_rejected_queries(app_db_path: Path) -> None:
    log_query(
        app_db_path,
        nl_question="how many permits",
        generated_sql="SELECT COUNT(*) FROM permits",
        validation_ok=True,
        rejection_reason=None,
        execution_time_ms=1.2,
        llm_backend="rule-based",
    )
    log_query(
        app_db_path,
        nl_question="drop permits",
        generated_sql="DROP TABLE permits",
        validation_ok=False,
        rejection_reason=RejectionReason.NOT_SELECT.value,
        execution_time_ms=None,
        llm_backend="malicious-fixture",
    )
    log_query(
        app_db_path,
        nl_question="delete permits",
        generated_sql="DELETE FROM permits",
        validation_ok=False,
        rejection_reason=RejectionReason.NOT_SELECT.value,
        execution_time_ms=None,
        llm_backend="malicious-fixture",
    )

    report = rejection_rate_report(app_db_path)
    assert report.total == 3
    assert report.rejected == 2
    assert round(report.rejection_rate, 4) == round(2 / 3, 4)
    assert report.rejected_by_reason[RejectionReason.NOT_SELECT.value] == 2


def test_report_as_dict_shape(app_db_path: Path) -> None:
    log_query(
        app_db_path,
        nl_question="q",
        generated_sql="SELECT 1",
        validation_ok=True,
        rejection_reason=None,
        execution_time_ms=0.5,
        llm_backend="rule-based",
    )
    d = rejection_rate_report(app_db_path).as_dict()
    assert set(d.keys()) == {
        "total_queries", "rejected", "accepted", "rejection_rate", "rejected_by_reason",
    }


def test_ask_writes_every_call_to_the_log(settings) -> None:
    """The end-to-end integration proving the operator-facing report
    reflects real `ask()` traffic, not just directly-inserted rows."""
    from text_to_sql_mcp.llm.rule_based import RuleBasedLLMClient
    from text_to_sql_mcp.service import ask

    class _MaliciousFixtureLLMClient:
        name = "malicious-fixture"

        def generate_sql(self, question: str, schema) -> str:
            return "DROP TABLE permits"

    ask("How many permits are there in total?", llm_client=RuleBasedLLMClient(), settings=settings)
    ask("Drop the permits table.", llm_client=_MaliciousFixtureLLMClient(), settings=settings)
    ask("What is the meaning of life?", llm_client=RuleBasedLLMClient(), settings=settings)

    report = rejection_rate_report(settings.app_db_abspath())
    assert report.total == 3
    assert report.rejected == 2  # the DROP TABLE attempt + the unanswerable question
    assert report.as_dict()["accepted"] == 1
