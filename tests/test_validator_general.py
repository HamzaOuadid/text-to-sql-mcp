"""General AST validator correctness tests: valid queries pass, schema
grounding rejects unknown tables/columns, and the missing-WHERE-on-large-
table check fires only where it should (spec milestone M3 + edge cases)."""

from __future__ import annotations

from text_to_sql_mcp.validator.ast_validator import validate_sql
from text_to_sql_mcp.validator.models import RejectionReason

THRESHOLD = 500


def _ok(sql, schema):
    return validate_sql(sql, schema, large_table_row_threshold=THRESHOLD)


# ---------------------------------------------------------------------
# Valid queries must pass
# ---------------------------------------------------------------------


def test_simple_select_passes(schema) -> None:
    r = _ok("SELECT * FROM departments", schema)
    assert r.ok, r.reason


def test_select_with_where_on_large_table_passes(schema) -> None:
    r = _ok("SELECT * FROM permits WHERE status = 'Issued'", schema)
    assert r.ok, r.reason


def test_join_query_passes(schema) -> None:
    r = _ok(
        "SELECT e.first_name, d.name FROM employees e "
        "JOIN departments d ON e.department_id = d.department_id",
        schema,
    )
    assert r.ok, r.reason


def test_cte_query_passes(schema) -> None:
    r = _ok(
        "WITH recent AS (SELECT * FROM permits WHERE status = 'Issued') "
        "SELECT * FROM recent LIMIT 10",
        schema,
    )
    assert r.ok, r.reason


def test_union_query_passes(schema) -> None:
    r = _ok(
        "SELECT name FROM departments UNION SELECT business_name FROM contractors",
        schema,
    )
    assert r.ok, r.reason


def test_group_by_aggregate_on_large_table_passes_without_where(schema) -> None:
    r = _ok(
        "SELECT permit_type, COUNT(*) AS c FROM permits GROUP BY permit_type",
        schema,
    )
    assert r.ok, r.reason


def test_pure_aggregate_on_large_table_passes_without_where(schema) -> None:
    r = _ok("SELECT COUNT(*) FROM permits", schema)
    assert r.ok, r.reason


def test_limit_on_large_table_passes_without_where(schema) -> None:
    r = _ok("SELECT * FROM permits LIMIT 25", schema)
    assert r.ok, r.reason


def test_subquery_in_where_passes(schema) -> None:
    r = _ok(
        "SELECT * FROM properties WHERE property_id IN "
        "(SELECT property_id FROM violations WHERE status = 'Open')",
        schema,
    )
    assert r.ok, r.reason


def test_column_alias_referenced_in_order_by_passes(schema) -> None:
    r = _ok(
        "SELECT permit_type, COUNT(*) AS cnt FROM permits GROUP BY permit_type ORDER BY cnt DESC",
        schema,
    )
    assert r.ok, r.reason


# ---------------------------------------------------------------------
# Schema grounding
# ---------------------------------------------------------------------


def test_unknown_table_is_rejected(schema) -> None:
    r = _ok("SELECT * FROM not_a_real_table", schema)
    assert not r.ok
    assert r.reason_code == RejectionReason.UNKNOWN_TABLE


def test_unknown_column_on_known_table_is_rejected(schema) -> None:
    r = _ok("SELECT this_column_does_not_exist FROM departments", schema)
    assert not r.ok
    assert r.reason_code == RejectionReason.UNKNOWN_COLUMN


def test_unknown_qualified_column_is_rejected(schema) -> None:
    r = _ok("SELECT d.nope FROM departments d", schema)
    assert not r.ok
    assert r.reason_code == RejectionReason.UNKNOWN_COLUMN


def test_cte_alias_is_not_treated_as_unknown_table(schema) -> None:
    r = _ok(
        "WITH x AS (SELECT * FROM departments) SELECT * FROM x",
        schema,
    )
    assert r.ok, r.reason


def test_ambiguous_unqualified_column_across_join_is_not_falsely_rejected(schema) -> None:
    # `status` exists on both permits and violations -- with two tables in
    # scope this is intentionally left unresolved rather than guessed at
    # (see _find_unknown_column docstring), so it must not be rejected.
    r = _ok(
        "SELECT p.permit_id FROM permits p JOIN violations v ON v.property_id = p.property_id "
        "WHERE status = 'Open'",
        schema,
    )
    assert r.ok, r.reason


# ---------------------------------------------------------------------
# Missing WHERE on large table
# ---------------------------------------------------------------------


def test_unfiltered_select_star_on_large_table_is_rejected(schema) -> None:
    r = _ok("SELECT * FROM permits", schema)
    assert not r.ok
    assert r.reason_code == RejectionReason.MISSING_WHERE_LARGE_TABLE


def test_unfiltered_select_star_on_small_table_passes(schema) -> None:
    r = _ok("SELECT * FROM departments", schema)
    assert r.ok, r.reason


def test_unfiltered_join_pulling_large_table_columns_is_rejected(schema) -> None:
    r = _ok(
        "SELECT p.permit_id, pr.address FROM permits p "
        "JOIN properties pr ON pr.property_id = p.property_id",
        schema,
    )
    assert not r.ok
    assert r.reason_code == RejectionReason.MISSING_WHERE_LARGE_TABLE


def test_missing_where_in_cte_body_is_caught(schema) -> None:
    r = _ok(
        "WITH everything AS (SELECT * FROM complaints) SELECT COUNT(*) FROM everything",
        schema,
    )
    assert not r.ok
    assert r.reason_code == RejectionReason.MISSING_WHERE_LARGE_TABLE
