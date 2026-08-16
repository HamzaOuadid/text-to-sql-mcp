"""Adversarial test suite (spec milestone M3 / testing plan): a set of
deliberately malicious or malformed SQL strings that MUST be rejected
100% of the time by the AST validator.

Per the acceptance criterion, this tests the validator directly against
SQL text -- simulating what a compromised, hallucinating, or successfully
prompt-injected LLM might hand back -- rather than relying on the LLM
itself declining to produce it. See test_service_ask.py for the
end-to-end version of the same guarantee, where a fixture LLM client is
deliberately made to *return* this kind of SQL for adversarial natural-
language prompts, proving the validator (not the model's own judgment)
is what blocks execution.
"""

from __future__ import annotations

import pytest

from text_to_sql_mcp.validator.ast_validator import validate_sql

THRESHOLD = 500

# 20 deliberately malicious/malformed SQL strings. The spec requires 10+;
# this covers every statement-type family (DML/DDL/admin), stacked-
# statement injection, comment-based smuggling, dangerous functions, and
# unparseable/garbage input.
ADVERSARIAL_SQL: list[str] = [
    "DROP TABLE permits",
    "DROP TABLE IF EXISTS permits",
    "DELETE FROM permits",
    "DELETE FROM permits WHERE 1=1",
    "UPDATE permits SET status = 'Completed'",
    "UPDATE contractors SET license_status = 'Active' WHERE contractor_id = 1",
    "INSERT INTO permits (permit_id, status) VALUES (999999, 'Issued')",
    "CREATE TABLE evil (x INTEGER)",
    "CREATE TABLE evil AS SELECT * FROM permits",
    "ALTER TABLE permits ADD COLUMN backdoor TEXT",
    "ALTER TABLE permits DROP COLUMN status",
    "PRAGMA table_info(permits)",
    "PRAGMA writable_schema = ON",
    "ATTACH DATABASE '/etc/passwd' AS pwned",
    "GRANT ALL PRIVILEGES ON permits TO public",
    "VACUUM",
    "REINDEX",
    "SELECT * FROM permits; DROP TABLE permits;",
    "SELECT * FROM permits WHERE status = 'Issued'; DELETE FROM permits;",
    "SELECT 1 AS x; INSERT INTO permits (permit_id) VALUES (1);",
    "SELECT load_extension('/tmp/evil.so')",
    "SELECT readfile('/etc/passwd')",
    "SELECT writefile('/tmp/pwn', 'x')",
    "SELECT * INTO shadow_permits FROM permits",
    "'; DROP TABLE permits; --",
    "not even valid sql at all !! ///",
    "",
    "   ",
    "SELECT * FROM permits WHERE status = 'Issued' AND 1=1) OR (1=1",
]


@pytest.mark.parametrize("sql", ADVERSARIAL_SQL, ids=lambda s: repr(s[:40]))
def test_adversarial_sql_is_always_rejected(sql, schema) -> None:
    result = validate_sql(sql, schema, large_table_row_threshold=THRESHOLD)
    assert result.ok is False, f"Adversarial SQL was NOT rejected: {sql!r}"
    assert result.reason is not None
    assert result.reason_code is not None


def test_adversarial_suite_has_at_least_ten_cases() -> None:
    assert len(ADVERSARIAL_SQL) >= 10


def test_rejection_rate_over_adversarial_suite_is_100_percent(schema) -> None:
    results = [
        validate_sql(sql, schema, large_table_row_threshold=THRESHOLD) for sql in ADVERSARIAL_SQL
    ]
    rejected = sum(1 for r in results if not r.ok)
    assert rejected == len(ADVERSARIAL_SQL)


# ---------------------------------------------------------------------
# Comment-based smuggling: the "hidden second statement" must still be
# caught as multiple-statements or simply never execute, because a SQL
# comment consumes everything after it on the line/block -- there is no
# way for the smuggled command to become a *separate* parsed statement
# without an unescaped semicolon, and if it does contain one, the
# multi-statement check catches it.
# ---------------------------------------------------------------------


def test_drop_hidden_entirely_inside_a_comment_is_inert(schema) -> None:
    # The would-be second statement never becomes a real statement at all --
    # it's text inside a SQL comment attached to the (single) SELECT node.
    # sqlglot's parser determines statement boundaries before any notion of
    # "what the comment says", so this is provably a single, safe SELECT:
    # there is nothing here for the execution layer to run except that one
    # SELECT. Re-rendering may reformat the comment style, but a comment is
    # never independently executable regardless of its wording.
    sql = "SELECT * FROM permits WHERE status='Issued' -- ; DROP TABLE permits"
    result = validate_sql(sql, schema, large_table_row_threshold=THRESHOLD)
    assert result.ok is True, result.reason


def test_drop_after_real_semicolon_following_a_comment_is_still_caught(schema) -> None:
    # Here the DROP is a genuine second statement (real semicolon, outside
    # the block comment) -- the multi-statement check must still catch it
    # even though a comment sits earlier in the string trying to look like
    # part of the same disguise.
    sql = (
        "SELECT * FROM permits /* ; DROP TABLE permits */ WHERE status='Issued'; "
        "DROP TABLE permits;"
    )
    result = validate_sql(sql, schema, large_table_row_threshold=THRESHOLD)
    assert result.ok is False
    assert result.reason_code is not None
