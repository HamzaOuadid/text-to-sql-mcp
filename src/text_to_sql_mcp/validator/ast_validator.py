"""AST-based SQL validator.

This is the core, novel piece of the project: a generated SQL string is
never trusted. It is parsed into a real syntax tree with sqlglot and run
through a sequence of structural checks before it is allowed anywhere near
a database connection. A query only executes if every check below passes.

Checks, in order:
    1. Parseable at all (rejects garbage / malformed SQL).
    2. Exactly one statement (rejects `SELECT ...; DROP TABLE ...` stacking).
    3. The statement's root node is a read-only query type
       (SELECT / UNION / INTERSECT / EXCEPT). This is an *allow-list*, not a
       blocklist -- DROP/DELETE/UPDATE/INSERT/CREATE/ALTER/PRAGMA/ATTACH/
       GRANT/etc. all parse to distinct sqlglot node types and are rejected
       by construction, regardless of what a compromised or hallucinating
       LLM tried to name them or how a prompt tried to disguise them.
    4. No `SELECT ... INTO <table>` (a SELECT statement that actually
       creates a table -- valid syntax in several SQL dialects).
    5. No call to a small denylist of dangerous SQLite functions
       (`load_extension`, `readfile`, `writefile`, ...).
    6. Every referenced table exists in the introspected schema (catches
       hallucinated/guessed table names, not just guessed-but-real ones).
    7. Every *resolvable* qualified column exists on its table (best
       effort -- see docstring on `_check_columns`).
    8. No large table (row_count > threshold) is scanned by a SELECT with
       no WHERE clause anywhere in its own scope (catches expensive full
       table scans even though the SQL is perfectly valid).

Any failure returns `ValidationResult(ok=False, reason=..., reason_code=...)`
and the query is never executed.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from .models import RejectionReason, Schema, ValidationResult

# Root node types considered safe, read-only queries.
_ALLOWED_ROOT_TYPES: tuple[type[exp.Expression], ...] = (
    exp.Select,
    exp.Union,
    exp.Intersect,
    exp.Except,
)

# SQLite (and general) functions that can read/write the filesystem or load
# arbitrary native code, even from inside an otherwise-valid SELECT.
_FORBIDDEN_FUNCTIONS = {
    "load_extension",
    "readfile",
    "writefile",
    "edit",
    "fts3_tokenizer",
}

DEFAULT_DIALECT = "sqlite"


def validate_sql(
    sql: str,
    schema: Schema,
    *,
    large_table_row_threshold: int = 500,
    dialect: str = DEFAULT_DIALECT,
) -> ValidationResult:
    """Validate a single candidate SQL string against `schema`.

    This is the function described in the spec's API contract:
    `validate_sql(sql: str, schema: Schema) -> ValidationResult`.
    """
    sql = (sql or "").strip()
    if not sql:
        return ValidationResult(
            ok=False,
            reason="Empty SQL string.",
            reason_code=RejectionReason.UNPARSEABLE,
        )

    # --- 1 & 2: parse, and require exactly one statement -----------------
    try:
        statements = [s for s in sqlglot.parse(sql, dialect=dialect) if s is not None]
    except ParseError as exc:
        return ValidationResult(
            ok=False,
            reason=f"SQL did not parse: {exc}",
            reason_code=RejectionReason.UNPARSEABLE,
        )
    except Exception as exc:  # sqlglot can raise other internal errors on garbage input
        return ValidationResult(
            ok=False,
            reason=f"SQL did not parse: {exc}",
            reason_code=RejectionReason.UNPARSEABLE,
        )

    if len(statements) == 0:
        return ValidationResult(
            ok=False,
            reason="Empty SQL string.",
            reason_code=RejectionReason.UNPARSEABLE,
        )
    if len(statements) > 1:
        return ValidationResult(
            ok=False,
            reason=(
                f"SQL contains {len(statements)} statements; only a single "
                "read-only statement is allowed (stacked/multi-statement "
                "SQL is rejected regardless of content)."
            ),
            reason_code=RejectionReason.MULTIPLE_STATEMENTS,
        )

    root = statements[0]

    # --- 3: statement type allow-list ------------------------------------
    if not isinstance(root, _ALLOWED_ROOT_TYPES):
        return ValidationResult(
            ok=False,
            reason=(
                f"Statement type '{type(root).__name__}' is not a read-only "
                "SELECT/UNION/INTERSECT/EXCEPT query. Only SELECT-family "
                "statements may be executed."
            ),
            reason_code=RejectionReason.NOT_SELECT,
        )

    # --- 4: reject SELECT ... INTO <table> --------------------------------
    for select_node in root.find_all(exp.Select):
        if select_node.args.get("into") is not None:
            return ValidationResult(
                ok=False,
                reason="SELECT ... INTO is not allowed (it creates a table).",
                reason_code=RejectionReason.FORBIDDEN_CONSTRUCT,
            )

    # --- 5: forbidden function calls --------------------------------------
    forbidden_hit = _find_forbidden_function(root)
    if forbidden_hit is not None:
        return ValidationResult(
            ok=False,
            reason=f"Call to forbidden function '{forbidden_hit}' is not allowed.",
            reason_code=RejectionReason.FORBIDDEN_CONSTRUCT,
        )

    # --- 6 & 7: schema grounding (tables, then columns) -------------------
    cte_names = {cte.alias.lower() for cte in root.find_all(exp.CTE) if cte.alias}

    unknown_table = _find_unknown_table(root, schema, cte_names)
    if unknown_table is not None:
        return ValidationResult(
            ok=False,
            reason=(
                f"Table '{unknown_table}' does not exist in the schema. "
                "Known tables: " + ", ".join(sorted(t.name for t in schema.tables))
            ),
            reason_code=RejectionReason.UNKNOWN_TABLE,
        )

    unknown_column = _find_unknown_column(root, schema, cte_names)
    if unknown_column is not None:
        table_hint, column_name = unknown_column
        if table_hint:
            reason = f"Column '{column_name}' does not exist on table '{table_hint}'."
        else:
            reason = f"Column '{column_name}' does not exist on any referenced table."
        return ValidationResult(
            ok=False,
            reason=reason,
            reason_code=RejectionReason.UNKNOWN_COLUMN,
        )

    # --- 8: missing WHERE clause on a large table -------------------------
    large_tables = schema.large_tables(large_table_row_threshold)
    if large_tables:
        offender = _find_unfiltered_large_table_scan(root, large_tables, cte_names)
        if offender is not None:
            table = schema.get_table(offender)
            row_count = table.row_count if table else "?"
            return ValidationResult(
                ok=False,
                reason=(
                    f"Query scans large table '{offender}' ({row_count} rows, "
                    f"threshold {large_table_row_threshold}) with no WHERE "
                    "clause. This is rejected as an unbounded full table scan; "
                    "add a filter or an explicit acknowledgement of the cost."
                ),
                reason_code=RejectionReason.MISSING_WHERE_LARGE_TABLE,
            )

    return ValidationResult(ok=True, normalized_sql=root.sql(dialect=dialect))


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _find_forbidden_function(root: exp.Expression) -> str | None:
    # Dangerous SQLite builtins (load_extension, readfile, writefile, ...) are
    # not modeled as their own sqlglot expression type -- they parse as a
    # generic function call (`exp.Anonymous`), which is also where any other
    # unrecognized/unknown function name would land.
    for node in root.find_all(exp.Anonymous):
        fn_name = (node.name or "").lower()
        if fn_name in _FORBIDDEN_FUNCTIONS:
            return fn_name
    return None


def _find_unknown_table(
    root: exp.Expression, schema: Schema, cte_names: set[str]
) -> str | None:
    known = schema.table_names()
    for table_node in root.find_all(exp.Table):
        name = table_node.name
        if not name:
            continue
        name_l = name.lower()
        if name_l in cte_names:
            continue  # reference to a CTE defined earlier in this query
        if name_l not in known:
            return name
    return None


def _build_alias_map(root: exp.Expression) -> dict[str, str]:
    """Map every table alias (or bare table name used without an alias)
    to the real table name it refers to."""
    alias_map: dict[str, str] = {}
    for table_node in root.find_all(exp.Table):
        real_name = table_node.name
        if not real_name:
            continue
        alias = table_node.alias or real_name
        alias_map[alias.lower()] = real_name
    return alias_map


def _known_expression_aliases(root: exp.Expression) -> set[str]:
    """Aliases introduced by `AS` anywhere in the query (SELECT-list output
    aliases, derived-table aliases, CTE names). Columns matching one of
    these (e.g. referenced later in ORDER BY / HAVING / an outer SELECT)
    are not checked against the physical schema."""
    names: set[str] = set()
    for alias_node in root.find_all(exp.Alias):
        if alias_node.alias:
            names.add(alias_node.alias.lower())
    for cte in root.find_all(exp.CTE):
        if cte.alias:
            names.add(cte.alias.lower())
    return names


def _find_unknown_column(
    root: exp.Expression, schema: Schema, cte_names: set[str]
) -> tuple[str | None, str] | None:
    """Best-effort column-existence check.

    Deliberately conservative: a column is flagged as unknown only when we
    can resolve it to a *specific* real table (via an explicit qualifier,
    or because exactly one physical table is referenced in the whole
    query) and it is not present on that table, nor a known output/CTE
    alias. Ambiguous or unresolvable references are left alone rather than
    risking a false-positive rejection of a legitimate query -- the table
    existence check above is the stricter, higher-confidence guard.
    """
    alias_map = _build_alias_map(root)
    known_aliases = _known_expression_aliases(root)
    physical_tables = [
        t.name for t in root.find_all(exp.Table) if t.name.lower() not in cte_names
    ]
    single_table = physical_tables[0] if len(set(t.lower() for t in physical_tables)) == 1 else None

    for col in root.find_all(exp.Column):
        col_name = col.name
        if not col_name or col_name == "*":
            continue
        if col_name.lower() in known_aliases:
            continue

        qualifier = col.table  # '' if unqualified
        if qualifier:
            qualifier_l = qualifier.lower()
            if qualifier_l in cte_names:
                continue  # can't introspect a CTE's projected columns
            real_table_name = alias_map.get(qualifier_l)
            if real_table_name is None:
                continue  # unresolvable alias (e.g. correlated outer scope) -- skip
            table = schema.get_table(real_table_name)
            if table is None:
                continue  # already reported as unknown table elsewhere
            if col_name.lower() not in table.column_names:
                return real_table_name, col_name
        else:
            if single_table is None:
                continue  # ambiguous -- multiple tables, can't safely resolve
            table = schema.get_table(single_table)
            if table is None:
                continue
            if col_name.lower() not in table.column_names:
                return single_table, col_name
    return None


def _select_returns_bounded_rows(select_node: exp.Select) -> bool:
    """True if this SELECT's own result size doesn't scale with the size
    of the table(s) it scans: it has a GROUP BY (aggregated down), a
    LIMIT, or every projected expression is aggregate-only (e.g.
    `COUNT(*)`, `SUM(x)`, `ROUND(100.0 * SUM(...) / COUNT(*), 2)` -- a
    single summary row, regardless of table size).

    This is what keeps the missing-WHERE check aimed at its actual
    target -- an accidental/unbounded raw-row full scan (`SELECT *`) --
    instead of also flagging completely ordinary reporting queries like
    "how many permits are there" or "permits per type", which legitimately
    have no WHERE clause and are not a cost problem: they still touch
    every row once, but they return one row (or one row per group), not
    one row per record in the table.
    """
    if select_node.args.get("group"):
        return True
    if select_node.args.get("limit"):
        return True

    projections = select_node.args.get("expressions") or []
    if not projections:
        return False

    for proj in projections:
        target = proj.this if isinstance(proj, exp.Alias) else proj
        if isinstance(target, exp.Star):
            return False  # SELECT * (or SELECT t.*) -- always row-level
        for col in target.find_all(exp.Column):
            if col.find_ancestor(exp.AggFunc) is None:
                return False  # a bare column outside any aggregate -> row-level
    return True


def _find_unfiltered_large_table_scan(
    root: exp.Expression, large_tables: set[str], cte_names: set[str]
) -> str | None:
    """Return the name of a large table that is scanned by some SELECT in
    the tree (at any nesting level -- CTE body, subquery, or top level)
    whose *own* scope has no WHERE clause and whose result is not
    otherwise bounded (see `_select_returns_bounded_rows`)."""
    for select_node in root.find_all(exp.Select):
        has_where = select_node.args.get("where") is not None
        if has_where:
            continue
        if _select_returns_bounded_rows(select_node):
            continue
        for table_node in select_node.find_all(exp.Table):
            # Only tables directly scoped to this SELECT, not a nested subquery's.
            if table_node.find_ancestor(exp.Select) is not select_node:
                continue
            name_l = table_node.name.lower()
            if name_l in cte_names:
                continue
            if name_l in large_tables:
                return table_node.name
    return None
