"""Schema-introspection tool.

Queries SQLite's own catalog (`sqlite_master` + `PRAGMA table_info`) --
the SQLite analogue of Postgres `information_schema` -- and returns a
structured `Schema` describing every table/column, plus row counts. This
is what grounds NL->SQL generation (the model is given the *real*
structure, not asked to guess table/column names) and what the AST
validator checks generated SQL against.

MCP tool contract: `list_schema() -> {tables: [{name, columns: [{name, type}]}]}`
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .db.connection import read_only_connection
from .validator.models import Column, Schema, Table

# Tables SQLite creates for its own bookkeeping (FTS shadow tables, etc.)
# or that we don't want exposed to the model -- excluded from list_schema.
_INTERNAL_TABLE_PREFIXES = ("sqlite_",)


def list_schema(db_path: Path | str) -> Schema:
    """Introspect `db_path` and return its table/column structure."""
    conn = read_only_connection(db_path)
    try:
        return _introspect(conn)
    finally:
        conn.close()


def _introspect(conn: sqlite3.Connection) -> Schema:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    )
    table_names = [
        row[0] for row in cur.fetchall() if not row[0].startswith(_INTERNAL_TABLE_PREFIXES)
    ]

    tables: list[Table] = []
    for name in table_names:
        col_rows = conn.execute(f"PRAGMA table_info('{name}')").fetchall()
        columns = [Column(name=r["name"], type=r["type"] or "TEXT") for r in col_rows]
        (count,) = conn.execute(f"SELECT COUNT(*) FROM '{name}'").fetchone()
        tables.append(Table(name=name, columns=columns, row_count=count))

    return Schema(tables=tables)


def schema_to_dict(schema: Schema) -> dict:
    """Render a `Schema` as the plain JSON-able dict shape from the API
    contract: `{tables: [{name, columns: [{name, type}]}]}`."""
    return {
        "tables": [
            {
                "name": t.name,
                "row_count": t.row_count,
                "columns": [{"name": c.name, "type": c.type} for c in t.columns],
            }
            for t in schema.tables
        ]
    }


def format_schema_for_prompt(schema: Schema) -> str:
    """Human/LLM-readable rendering of the schema, used as grounding
    context in the NL->SQL generation prompt."""
    lines = []
    for t in schema.tables:
        cols = ", ".join(f"{c.name} {c.type}" for c in t.columns)
        lines.append(f"{t.name}({cols})  -- {t.row_count} rows")
    return "\n".join(lines)
