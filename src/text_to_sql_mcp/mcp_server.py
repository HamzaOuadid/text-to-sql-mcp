"""MCP server wrapper.

Exposes exactly the two tools from the spec's API contract:

    list_schema() -> {tables: [{name, columns: [{name, type}]}]}
    ask(question: str) -> {sql, rows, rejected, rejection_reason}

Built with the official `mcp` Python SDK's FastMCP high-level API. See
tests/test_mcp_server.py for an end-to-end test that drives this server
through a real `mcp.ClientSession` (in-memory transport) rather than
calling the underlying Python functions directly.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .config import Settings, get_settings
from .introspection import list_schema as _list_schema
from .introspection import schema_to_dict
from .llm.factory import get_llm_client
from .service import ask as _ask

mcp = FastMCP("text-to-sql-mcp")


def _settings() -> Settings:
    return get_settings()


@mcp.tool()
def list_schema() -> dict:
    """Return the introspected schema of the civic dataset: every table,
    its columns (name + type), and its row count. Use this to ground any
    SQL you generate -- only reference tables/columns that appear here."""
    settings = _settings()
    schema = _list_schema(settings.civic_db_abspath())
    return schema_to_dict(schema)


@mcp.tool()
def ask(question: str) -> dict:
    """Answer a natural-language question about the civic dataset.

    Translates `question` into SQL, validates it via AST analysis
    (rejecting anything that is not a safe read-only SELECT, references
    an unknown table/column, or does an unfiltered scan of a large
    table), and -- only if validation passes -- executes it and returns
    the rows. Returns `{sql, rows, rejected, rejection_reason}`.
    """
    settings = _settings()
    llm_client = get_llm_client(settings)
    result = _ask(question, llm_client=llm_client, settings=settings)
    return {
        "sql": result.sql,
        "rows": result.rows,
        "rejected": result.rejected,
        "rejection_reason": result.rejection_reason,
        "truncated": result.truncated,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
