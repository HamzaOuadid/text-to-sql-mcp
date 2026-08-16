"""Orchestrates the end-to-end `ask()` flow: NL question -> LLM-generated
SQL -> AST validation -> (only if valid) execution -> logging.

This is the one place that ties the whole pipeline together, and it is
what both the CLI and the MCP server call. The contract matches the
spec's API section: `ask(question: str) -> {sql, rows, rejected,
rejection_reason}`. Every call -- accepted or rejected -- is written to
`query_log`, which is what makes the operator-facing rejection-rate
report (see query_log.py) reflect real usage instead of only the eval
harness's synthetic run.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from .config import Settings
from .execution import execute_query
from .introspection import list_schema
from .llm.base import LLMClient, LLMGenerationError
from .llm.prompt import AMBIGUOUS_PREFIX
from .query_log import log_query
from .validator.ast_validator import validate_sql
from .validator.models import RejectionReason, Schema


class AskResult(BaseModel):
    sql: str | None
    rows: list[dict]
    rejected: bool
    rejection_reason: str | None
    rejection_reason_code: str | None = None
    truncated: bool = False
    execution_time_ms: float | None = None
    llm_backend: str


def ask(
    question: str,
    *,
    llm_client: LLMClient,
    settings: Settings,
    schema: Schema | None = None,
) -> AskResult:
    """Answer one natural-language question end to end.

    `schema` can be pre-computed and passed in (e.g. by the eval runner,
    which calls this once per question) to avoid re-introspecting the
    database on every call; if omitted it is introspected fresh.
    """
    civic_db = settings.civic_db_abspath()
    app_db = settings.app_db_abspath()
    if schema is None:
        schema = list_schema(civic_db)

    # --- 1. Generate a SQL candidate -------------------------------------
    try:
        candidate_sql = llm_client.generate_sql(question, schema)
    except LLMGenerationError as exc:
        result = AskResult(
            sql=None,
            rows=[],
            rejected=True,
            rejection_reason=str(exc),
            rejection_reason_code=RejectionReason.GENERATION_FAILED.value,
            llm_backend=llm_client.name,
        )
        _log(app_db, question, result)
        return result

    # --- 2. Ambiguity: the model chose not to guess -----------------------
    if candidate_sql.strip().startswith(AMBIGUOUS_PREFIX):
        clarification = candidate_sql.strip()[len(AMBIGUOUS_PREFIX):].strip()
        result = AskResult(
            sql=candidate_sql,
            rows=[],
            rejected=True,
            rejection_reason=(
                "Question is ambiguous and was not silently resolved to one "
                f"interpretation. Clarification needed: {clarification}"
            ),
            rejection_reason_code="ambiguous_question",
            llm_backend=llm_client.name,
        )
        _log(app_db, question, result)
        return result

    # --- 3. AST validation --------------------------------------------------
    validation = validate_sql(
        candidate_sql,
        schema,
        large_table_row_threshold=settings.large_table_row_threshold,
    )
    if not validation.ok:
        result = AskResult(
            sql=candidate_sql,
            rows=[],
            rejected=True,
            rejection_reason=validation.reason,
            rejection_reason_code=validation.reason_code.value if validation.reason_code else None,
            llm_backend=llm_client.name,
        )
        _log(app_db, question, result)
        return result

    # --- 4. Execute only validator-approved SQL ------------------------------
    exec_result = execute_query(
        civic_db, validation.normalized_sql or candidate_sql, max_rows=settings.max_result_rows
    )
    result = AskResult(
        sql=candidate_sql,
        rows=exec_result.rows,
        rejected=False,
        rejection_reason=None,
        truncated=exec_result.truncated,
        execution_time_ms=exec_result.execution_time_ms,
        llm_backend=llm_client.name,
    )
    _log(app_db, question, result)
    return result


def _log(app_db: Path, question: str, result: AskResult) -> None:
    log_query(
        app_db,
        nl_question=question,
        generated_sql=result.sql,
        validation_ok=not result.rejected,
        rejection_reason=result.rejection_reason_code or result.rejection_reason,
        execution_time_ms=result.execution_time_ms,
        llm_backend=result.llm_backend,
    )
