"""Execution layer: runs only validator-approved SQL, against a
strictly read-only connection (see db/connection.py). This function must
never be called with SQL that hasn't already passed `validate_sql` --
callers are `service.ask()` and tests exercising this layer directly.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .db.connection import read_only_connection


class ExecutionResult:
    def __init__(self, rows: list[dict[str, Any]], truncated: bool, execution_time_ms: float):
        self.rows = rows
        self.truncated = truncated
        self.execution_time_ms = execution_time_ms


def execute_query(
    db_path: Path | str,
    sql: str,
    *,
    max_rows: int = 200,
) -> ExecutionResult:
    """Execute `sql` (assumed already validated) against `db_path`
    read-only and return up to `max_rows` rows."""
    conn = read_only_connection(db_path)
    start = time.perf_counter()
    try:
        cursor = conn.execute(sql)
        raw_rows = cursor.fetchmany(max_rows + 1)
        elapsed_ms = (time.perf_counter() - start) * 1000
        truncated = len(raw_rows) > max_rows
        rows = [dict(r) for r in raw_rows[:max_rows]]
        return ExecutionResult(rows=rows, truncated=truncated, execution_time_ms=elapsed_ms)
    finally:
        conn.close()
