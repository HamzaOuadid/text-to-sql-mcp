"""Shared data models: schema description and validation results."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Column(BaseModel):
    name: str
    type: str


class Table(BaseModel):
    name: str
    columns: list[Column]
    row_count: int = 0

    @property
    def column_names(self) -> set[str]:
        return {c.name.lower() for c in self.columns}


class Schema(BaseModel):
    """In-memory description of the target database's structure, as
    returned by the schema-introspection tool. This is what grounds both
    NL->SQL generation and AST-level schema validation."""

    tables: list[Table]

    def table_names(self) -> set[str]:
        return {t.name.lower() for t in self.tables}

    def get_table(self, name: str) -> Table | None:
        name_l = name.lower()
        for t in self.tables:
            if t.name.lower() == name_l:
                return t
        return None

    def large_tables(self, threshold: int) -> set[str]:
        return {t.name.lower() for t in self.tables if t.row_count > threshold}


class RejectionReason(str, Enum):
    """Machine-readable category for why a query was rejected. Used both
    for user-facing messages and for the rejection-rate breakdown the
    operator-facing reporting relies on."""

    UNPARSEABLE = "unparseable"
    MULTIPLE_STATEMENTS = "multiple_statements"
    NOT_SELECT = "not_select"
    FORBIDDEN_CONSTRUCT = "forbidden_construct"
    UNKNOWN_TABLE = "unknown_table"
    UNKNOWN_COLUMN = "unknown_column"
    MISSING_WHERE_LARGE_TABLE = "missing_where_large_table"
    GENERATION_FAILED = "generation_failed"


class ValidationResult(BaseModel):
    ok: bool
    reason: str | None = None
    reason_code: RejectionReason | None = None
    normalized_sql: str | None = Field(
        default=None, description="Canonical re-rendered SQL, when parsing succeeded."
    )
