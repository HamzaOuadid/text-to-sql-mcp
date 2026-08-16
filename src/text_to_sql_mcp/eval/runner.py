"""Eval harness: runs the labelled question set end to end through
`service.ask()` and reports accuracy broken down by difficulty and by
join-heaviness (spec section 9/10), plus the rejection rate the
validator produced along the way -- reported separately, never folded
into the accuracy number, per the "operator" user story.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Settings
from ..execution import execute_query
from ..introspection import list_schema
from ..llm.base import LLMClient
from ..service import ask
from ..validator.ast_validator import validate_sql
from .questions import QUESTIONS, EvalQuestion


@dataclass
class QuestionResult:
    question: EvalQuestion
    correct: bool
    rejected: bool
    rejection_reason: str | None
    actual_sql: str | None
    detail: str = ""


@dataclass
class EvalReport:
    results: list[QuestionResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def correct(self) -> int:
        return sum(1 for r in self.results if r.correct)

    @property
    def accuracy(self) -> float:
        return (self.correct / self.total) if self.total else 0.0

    @property
    def rejected_count(self) -> int:
        return sum(1 for r in self.results if r.rejected)

    @property
    def rejection_rate(self) -> float:
        return (self.rejected_count / self.total) if self.total else 0.0

    def accuracy_by_difficulty(self) -> dict[str, dict[str, float | int]]:
        return self._grouped_accuracy(lambda r: r.question.difficulty)

    def accuracy_by_join_heaviness(self) -> dict[str, dict[str, float | int]]:
        return self._grouped_accuracy(
            lambda r: "join_heavy" if r.question.is_join_heavy else "simple"
        )

    def _grouped_accuracy(self, key_fn) -> dict[str, dict[str, float | int]]:
        groups: dict[str, list[QuestionResult]] = {}
        for r in self.results:
            groups.setdefault(key_fn(r), []).append(r)
        out: dict[str, dict[str, float | int]] = {}
        for key, items in groups.items():
            n_correct = sum(1 for i in items if i.correct)
            out[key] = {
                "total": len(items),
                "correct": n_correct,
                "accuracy": round(n_correct / len(items), 4) if items else 0.0,
            }
        return out

    def as_dict(self) -> dict:
        return {
            "total_questions": self.total,
            "correct": self.correct,
            "accuracy": round(self.accuracy, 4),
            "rejected": self.rejected_count,
            "rejection_rate": round(self.rejection_rate, 4),
            "by_difficulty": self.accuracy_by_difficulty(),
            "by_join_heaviness": self.accuracy_by_join_heaviness(),
        }


def _rows_as_comparable(rows: list[dict]) -> list[tuple]:
    normalized = []
    for row in rows:
        normalized.append(tuple(row[k] for k in sorted(row.keys())))
    return sorted(normalized, key=repr)


def run_eval(settings: Settings, llm_client: LLMClient) -> EvalReport:
    civic_db = settings.civic_db_abspath()
    schema = list_schema(civic_db)
    report = EvalReport()

    for question in QUESTIONS:
        result = ask(question.nl_question, llm_client=llm_client, settings=settings, schema=schema)

        if question.is_ambiguous:
            correct = result.rejected and result.rejection_reason_code == "ambiguous_question"
            report.results.append(
                QuestionResult(
                    question=question,
                    correct=correct,
                    rejected=result.rejected,
                    rejection_reason=result.rejection_reason,
                    actual_sql=result.sql,
                    detail="expected ambiguity to be flagged, not silently resolved",
                )
            )
            continue

        if result.rejected:
            report.results.append(
                QuestionResult(
                    question=question,
                    correct=False,
                    rejected=True,
                    rejection_reason=result.rejection_reason,
                    actual_sql=result.sql,
                )
            )
            continue

        assert question.expected_sql is not None
        gold_validation = validate_sql(
            question.expected_sql, schema, large_table_row_threshold=settings.large_table_row_threshold
        )
        gold_sql = gold_validation.normalized_sql or question.expected_sql
        gold_exec = execute_query(civic_db, gold_sql, max_rows=settings.max_result_rows)

        correct = _rows_as_comparable(result.rows) == _rows_as_comparable(gold_exec.rows)
        report.results.append(
            QuestionResult(
                question=question,
                correct=correct,
                rejected=False,
                rejection_reason=None,
                actual_sql=result.sql,
                detail="" if correct else "returned rows did not match the gold query's rows",
            )
        )

    return report
