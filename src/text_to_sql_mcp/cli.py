"""Command-line interface.

    text-to-sql-mcp init-db          # build data/civic.db + data/app.db
    text-to-sql-mcp schema           # print the introspected schema
    text-to-sql-mcp ask "..."        # ask one question
    text-to-sql-mcp eval             # run the labelled eval set, print report
"""

from __future__ import annotations

import json

import typer

from .config import get_settings
from .db.seed import build_civic_db, init_app_db
from .introspection import list_schema as _list_schema
from .introspection import schema_to_dict
from .llm.factory import get_llm_client
from .service import ask as _ask

app = typer.Typer(add_completion=False, help="Text-to-SQL MCP server with AST-based validation.")


@app.command("init-db")
def init_db(force: bool = typer.Option(False, help="Recreate the databases even if they exist.")) -> None:
    """Create and seed the civic demo database and the app metadata database."""
    settings = get_settings()
    civic_path = settings.civic_db_abspath()
    app_path = settings.app_db_abspath()
    build_civic_db(civic_path, force=force)
    init_app_db(app_path, force=force)
    typer.echo(f"civic database ready at {civic_path}")
    typer.echo(f"app database ready at {app_path}")


@app.command("schema")
def schema_cmd() -> None:
    """Print the introspected schema as JSON."""
    settings = get_settings()
    schema = _list_schema(settings.civic_db_abspath())
    typer.echo(json.dumps(schema_to_dict(schema), indent=2))


@app.command("ask")
def ask_cmd(question: str) -> None:
    """Ask one natural-language question and print the result."""
    settings = get_settings()
    llm_client = get_llm_client(settings)
    result = _ask(question, llm_client=llm_client, settings=settings)
    typer.echo(f"backend:  {result.llm_backend}")
    typer.echo(f"sql:      {result.sql}")
    typer.echo(f"rejected: {result.rejected}")
    if result.rejected:
        typer.echo(f"reason:   {result.rejection_reason}")
    else:
        typer.echo(f"rows ({len(result.rows)}{'+' if result.truncated else ''}):")
        typer.echo(json.dumps(result.rows, indent=2, default=str))


@app.command("eval")
def eval_cmd() -> None:
    """Run the labelled 25-question eval set and print accuracy + rejection stats."""
    from .eval.runner import run_eval

    settings = get_settings()
    llm_client = get_llm_client(settings)
    typer.echo(f"Running eval with backend: {llm_client.name}")
    report = run_eval(settings, llm_client)
    typer.echo(json.dumps(report.as_dict(), indent=2))


if __name__ == "__main__":
    app()
