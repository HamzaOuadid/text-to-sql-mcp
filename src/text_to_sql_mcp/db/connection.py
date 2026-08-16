"""Connection helpers.

Two separate SQLite files are used deliberately:

- `civic.db` -- the target dataset that generated SQL actually runs
  against. Opened in **read-only** mode (`mode=ro` URI + `PRAGMA
  query_only = ON`) for every query execution. This is the SQLite
  equivalent of the spec's "read-only database role/connection so even a
  validator bug can't cause damage" -- defense in depth alongside the AST
  validator, not a replacement for it.
- `app.db` -- read/write metadata (eval_questions, query_log). Never used
  to execute generated SQL.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def read_only_connection(db_path: Path | str) -> sqlite3.Connection:
    """Open `db_path` strictly read-only. Any attempted write -- even one
    that slipped past the AST validator -- fails at the database layer."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(
            f"Civic database not found at {db_path}. Run "
            "`text-to-sql-mcp init-db` first."
        )
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def read_write_connection(db_path: Path | str) -> sqlite3.Connection:
    """Open `db_path` read/write. Used only for the app-metadata database
    (eval_questions, query_log), never for executing generated SQL."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn
