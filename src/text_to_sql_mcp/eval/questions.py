"""The labelled evaluation question set -- re-exported here as the
spec-named module (`eval_questions`, milestone M4). The actual data lives
in `text_to_sql_mcp.fixtures`, a dependency-free leaf module, so that
`llm.rule_based` (the deterministic offline backend) can share the exact
same fixture data without creating an import cycle between the `eval`
and `llm` packages.
"""

from __future__ import annotations

from ..fixtures import QUESTIONS, Difficulty, EvalQuestion

__all__ = ["EvalQuestion", "QUESTIONS", "Difficulty"]
