"""`query_log` persistence and the operator-facing rejection-rate report.

Spec user story: "As an operator, I can see how often the validator is
actually catching something" -- the rejection rate must be logged and
reported *separately* from the accuracy metric (that's eval/runner.py's
job). This module owns the logging half and the aggregate reporting half.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db.connection import read_write_connection


def log_query(
    app_db_path: Path | str,
    *,
    nl_question: str,
    generated_sql: str | None,
    validation_ok: bool,
    rejection_reason: str | None,
    execution_time_ms: float | None,
    llm_backend: str,
) -> None:
    conn = read_write_connection(app_db_path)
    try:
        conn.execute(
            "INSERT INTO query_log (timestamp, nl_question, generated_sql, validation_ok, "
            "rejection_reason, execution_time_ms, llm_backend) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                nl_question,
                generated_sql,
                int(validation_ok),
                rejection_reason,
                execution_time_ms,
                llm_backend,
            ),
        )
        conn.commit()
    finally:
        conn.close()


class RejectionRateReport:
    def __init__(
        self,
        total: int,
        rejected: int,
        rejected_by_reason: dict[str, int],
    ):
        self.total = total
        self.rejected = rejected
        self.rejected_by_reason = rejected_by_reason

    @property
    def rejection_rate(self) -> float:
        return (self.rejected / self.total) if self.total else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_queries": self.total,
            "rejected": self.rejected,
            "accepted": self.total - self.rejected,
            "rejection_rate": round(self.rejection_rate, 4),
            "rejected_by_reason": self.rejected_by_reason,
        }


def rejection_rate_report(app_db_path: Path | str) -> RejectionRateReport:
    """Read back everything in `query_log` and compute the operator-facing
    rejection-rate breakdown -- independent of, and never mixed into, the
    accuracy metric from the eval harness."""
    conn = read_write_connection(app_db_path)
    try:
        rows = conn.execute(
            "SELECT validation_ok, rejection_reason FROM query_log"
        ).fetchall()
    finally:
        conn.close()

    total = len(rows)
    rejected = sum(1 for r in rows if not r["validation_ok"])
    by_reason: dict[str, int] = {}
    for r in rows:
        if not r["validation_ok"]:
            reason = r["rejection_reason"] or "unknown"
            by_reason[reason] = by_reason.get(reason, 0) + 1
    return RejectionRateReport(total=total, rejected=rejected, rejected_by_reason=by_reason)
