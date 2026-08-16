"""Execution-layer tests: read-only enforcement and row-limit truncation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from text_to_sql_mcp.execution import execute_query


def test_execute_query_returns_rows(civic_db_path: Path) -> None:
    result = execute_query(civic_db_path, "SELECT * FROM departments", max_rows=100)
    assert len(result.rows) == 6
    assert result.truncated is False


def test_execute_query_truncates_at_max_rows(civic_db_path: Path) -> None:
    result = execute_query(civic_db_path, "SELECT * FROM permits", max_rows=10)
    assert len(result.rows) == 10
    assert result.truncated is True


def test_read_only_connection_rejects_writes(civic_db_path: Path) -> None:
    """Defense in depth: even if a write statement somehow reached this
    layer (e.g. a validator bug), the connection itself refuses it."""
    with pytest.raises(sqlite3.OperationalError):
        execute_query(civic_db_path, "DELETE FROM permits", max_rows=10)


def test_missing_database_raises_clear_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        execute_query(tmp_path / "does_not_exist.db", "SELECT 1", max_rows=10)
