"""Schema-introspection tool tests (spec milestone M1)."""

from __future__ import annotations

from pathlib import Path

from text_to_sql_mcp.introspection import format_schema_for_prompt, list_schema, schema_to_dict


def test_list_schema_returns_all_tables(civic_db_path: Path) -> None:
    schema = list_schema(civic_db_path)
    names = schema.table_names()
    expected = {
        "departments", "employees", "owners", "zones", "properties",
        "contractors", "licenses", "permits", "inspections", "violations",
        "complaints", "payments",
    }
    assert expected <= names


def test_list_schema_reports_accurate_columns(civic_db_path: Path) -> None:
    schema = list_schema(civic_db_path)
    permits = schema.get_table("permits")
    assert permits is not None
    col_names = permits.column_names
    assert {"permit_id", "property_id", "contractor_id", "status", "issue_date"} <= col_names


def test_list_schema_reports_accurate_row_counts(civic_db_path: Path) -> None:
    schema = list_schema(civic_db_path)
    permits = schema.get_table("permits")
    departments = schema.get_table("departments")
    assert permits is not None and departments is not None
    # permits is seeded with 2600 rows, departments with a fixed 6.
    assert permits.row_count == 2600
    assert departments.row_count == 6


def test_large_tables_uses_threshold(civic_db_path: Path) -> None:
    schema = list_schema(civic_db_path)
    large = schema.large_tables(threshold=500)
    assert "permits" in large
    assert "complaints" in large
    assert "departments" not in large
    assert "employees" not in large


def test_schema_to_dict_matches_api_contract(civic_db_path: Path) -> None:
    schema = list_schema(civic_db_path)
    d = schema_to_dict(schema)
    assert "tables" in d
    table = d["tables"][0]
    assert "name" in table and "columns" in table
    assert "name" in table["columns"][0] and "type" in table["columns"][0]


def test_format_schema_for_prompt_is_nonempty(civic_db_path: Path) -> None:
    schema = list_schema(civic_db_path)
    text = format_schema_for_prompt(schema)
    assert "permits" in text
    assert "complaints" in text
