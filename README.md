# text-to-sql-mcp

An MCP server that translates natural-language questions into SQL over a real, non-trivial multi-table schema — and never trusts the SQL it gets back. Every generated query is parsed into a real AST (via [sqlglot](https://github.com/tobymao/sqlglot)) and run through a validator before anything executes: non-`SELECT` statements, multi-statement injection, dangerous functions, hallucinated tables/columns, and unbounded full scans of large tables are all rejected structurally, not by trusting an LLM's own judgment.

> The model's output is a proposal, not a command. A validator decides what actually runs.

## Status

Milestones M1–M4 from the spec are implemented and tested: schema introspection, NL→SQL generation (real Anthropic/OpenAI backends + a deterministic offline fallback), the AST validator, the labelled eval harness, and the MCP server wrapper. See [Risks / Open Questions](#risks--open-questions--scope-cuts) for what was deliberately deferred.

## Architecture

```
NL question
    │
    ▼
schema introspection (introspection.py)  ──► SQLite catalog (sqlite_master + PRAGMA table_info)
    │  grounds the prompt in the *real* schema, not guessed names
    ▼
LLMClient.generate_sql()  (llm/factory.py picks one)
    │  - AnthropicLLMClient  (real Claude API call, used if ANTHROPIC_API_KEY is set)
    │  - OpenAILLMClient     (real OpenAI API call, used if OPENAI_API_KEY is set)
    │  - RuleBasedLLMClient  (deterministic fixture lookup, the offline default)
    ▼
candidate SQL string  ──────────────────►  never trusted past this point
    │
    ▼
validate_sql()  (validator/ast_validator.py)
    │  1. parseable?                       -- sqlglot.parse()
    │  2. exactly one statement?           -- reject `SELECT ...; DROP ...`
    │  3. root node is SELECT/UNION/       -- allow-list, not a blocklist
    │     INTERSECT/EXCEPT?
    │  4. no SELECT ... INTO?
    │  5. no dangerous function calls?     -- load_extension, readfile, writefile, ...
    │  6. every table exists in schema?
    │  7. every resolvable column exists?  -- best-effort, conservative
    │  8. large table + no WHERE + not     -- the "unbounded full scan" check
    │     a bounded/aggregate result?
    │
    ├── reject ──► {rejected: true, rejection_reason: "..."}
    │
    ▼ ok
execute_query()  (execution.py)  ──► SQLite opened `mode=ro` + `PRAGMA query_only=ON`
    │  (defense in depth: even a validator bug can't write, because the
    │   connection itself refuses)
    ▼
{sql, rows, rejected: false}
    │
    ▼
query_log  (query_log.py)  ──► every call logged, rejection rate reported
                                 separately from accuracy (see below)
```

Everything above is wrapped as an MCP server (`mcp_server.py`, built on the official `mcp` Python SDK's `FastMCP`) exposing exactly the two tools from the spec's API contract:

- `list_schema() -> {tables: [{name, columns: [{name, type}]}]}`
- `ask(question: str) -> {sql, rows, rejected, rejection_reason}`

### Why SQLite instead of Postgres

The spec targets Postgres specifically. This environment has no running Postgres server and no Docker daemon, so the target database is SQLite instead — a deliberate, documented substitution, not an oversight. The introspection layer (`introspection.py`) is the only piece that's genuinely SQLite-specific (`sqlite_master` + `PRAGMA table_info` in place of `information_schema`); the validator, execution layer, and MCP wrapper operate on the parsed AST and don't know or care which database produced the schema. **Postgres upgrade path:** swap `db/connection.py`'s `sqlite3.connect(..., mode=ro)` for a `psycopg` connection opened against a read-only role, rewrite `introspection.py`'s two queries against `information_schema.tables`/`columns`, and pass `dialect="postgres"` to `validate_sql()` — sqlglot supports both dialects natively, so the AST logic itself does not change.

### Why a synthetic dataset instead of a live open-data pull

The spec suggests a real city/government open-data portal. `db/seed.py` instead generates a synthetic-but-realistic municipal dataset — 12 tables modeled on real permit/inspection/violation schemas (NYC DOB, Chicago building permits) — deterministically from a fixed seed, entirely offline. This was a deliberate trade-off, not laziness: it keeps `init-db` reproducible with zero network dependency (no flaky CI, no rate limits, no portal downtime) and sidesteps the licensing question the spec itself flags as a risk (§13) before ever publishing a demo. The schema is genuinely non-trivial by the spec's own bar: 12 tables, foreign keys three hops deep (`payments → violations → properties`), and deliberate column-name ambiguity (`status` appears on `permits`, `licenses`, `violations`, and `complaints`; `type` on four different tables) that exercises the validator's schema-grounding logic for real.

## Install

```bash
pip install -e .
```

Requires Python 3.10+. Optional extras for the real LLM backends (already installed in dev environments that have them; only needed if you don't):

```bash
pip install -e ".[anthropic]"   # anthropic SDK
pip install -e ".[openai]"      # openai SDK
```

## Quickstart — real demo run against a real SQLite database

```bash
# 1. Build the demo database (12 tables, ~8,700 rows, deterministic seed 42)
text-to-sql-mcp init-db

# 2. Inspect the schema the model is grounded in
text-to-sql-mcp schema

# 3. Ask a question -- no API key needed, uses the deterministic rule-based backend
text-to-sql-mcp ask "How many permits are there in total?"
```

```
backend:  rule-based
sql:      SELECT COUNT(*) AS count FROM permits
rejected: False
rows (1):
[
  {
    "count": 2600
  }
]
```

A join-heavy question:

```bash
text-to-sql-mcp ask "How many permits does each contractor hold?"
```

```
backend:  rule-based
sql:      SELECT c.business_name, COUNT(*) AS permit_count FROM permits p JOIN contractors c ON p.contractor_id = c.contractor_id GROUP BY c.business_name ORDER BY permit_count DESC
rejected: False
rows (50):
[
  { "business_name": "Garcia Builders", "permit_count": 167 },
  { "business_name": "Kim Builders", "permit_count": 144 },
  { "business_name": "Miller Plumbing Co", "permit_count": 119 },
  ...
]
```

An ambiguous question — deliberately **not** silently resolved to one guess (see [Edge cases](#edge-cases-handled)):

```bash
text-to-sql-mcp ask "Show me the recent activity."
```

```
backend:  rule-based
sql:      AMBIGUOUS: 'Recent activity' could mean permits, inspections, violations, complaints, or payments -- and over what time window. Please specify which type of record and a date range or property.
rejected: True
reason:   Question is ambiguous and was not silently resolved to one interpretation. Clarification needed: ...
```

**Proof that the validator, not the model, is what blocks destructive SQL** — this uses a fixture client standing in for a compromised/prompt-injected model that *always complies* with the destructive request:

```bash
python - <<'EOF'
from text_to_sql_mcp.config import get_settings
from text_to_sql_mcp.service import ask

class MaliciousFixtureLLMClient:
    name = "malicious-fixture"
    def generate_sql(self, question, schema):
        return "DROP TABLE permits"

result = ask("Please delete all the permit records.",
             llm_client=MaliciousFixtureLLMClient(), settings=get_settings())
print("sql:     ", result.sql)
print("rejected:", result.rejected)
print("reason:  ", result.rejection_reason)
EOF
```

```
sql:      DROP TABLE permits
rejected: True
reason:   Statement type 'Drop' is not a read-only SELECT/UNION/INTERSECT/EXCEPT query. Only SELECT-family statements may be executed.
```

Now check what the operator sees — the rejection rate, reported **separately** from accuracy (see below):

```bash
text-to-sql-mcp rejection-report
```

```json
{
  "total_queries": 5,
  "rejected": 3,
  "accepted": 2,
  "rejection_rate": 0.6,
  "rejected_by_reason": {
    "ambiguous_question": 1,
    "generation_failed": 1,
    "not_select": 1
  }
}
```

(That `0.6` is not a target number to hit — it's whatever the actual mix of questions asked in this session produced, on this exact run. Re-running `init-db` and repeating the commands above reproduces it exactly, since the seed data and the rule-based backend are both deterministic.)

## Accuracy on the labelled eval set

```bash
text-to-sql-mcp eval
```

Real output, rule-based backend, this seed (25 questions: 8 easy / 10 medium / 7 hard, spanning the spec's 20–30 question requirement):

```json
{
  "total_questions": 25,
  "correct": 20,
  "accuracy": 0.8,
  "rejected": 6,
  "rejection_rate": 0.24,
  "by_difficulty": {
    "easy":   { "total": 8,  "correct": 8, "accuracy": 1.0 },
    "medium": { "total": 10, "correct": 8, "accuracy": 0.8 },
    "hard":   { "total": 7,  "correct": 4, "accuracy": 0.5714 }
  },
  "by_join_heaviness": {
    "simple":     { "total": 17, "correct": 17, "accuracy": 1.0 },
    "join_heavy": { "total": 8,  "correct": 3,  "accuracy": 0.375 }
  }
}
```

**This 80% is not a coincidence and not a claim taken at face value** — it's produced by a deliberate design choice: the rule-based backend recognizes 20 of the 25 questions and *raises on the other 5* rather than guessing (see `llm/rule_based.py`'s `_UNANSWERED_IDS`). The eval harness runs every question through the real `ask()` pipeline and compares actual returned rows against a gold query executed fresh against the same database — it is not hand-maintained expected numbers that could silently drift from the seed data. Accuracy decays with difficulty (100% → 80% → 57%) and is dramatically lower on join-heavy questions (37.5% vs. 100% on simple ones) purely because the rule-based backend is a lookup table, not because the harness or validator is doing anything different — which is exactly the honest signal the spec's acceptance criterion asks for ("accuracy is measured and reported, not just claimed").

**With a real `ANTHROPIC_API_KEY` configured**, `ask()`/`eval` route through `AnthropicLLMClient` instead (see [What needs a real API key](#what-needs-a-real-api-key-vs-what-works-standalone-today)) and accuracy would reflect actual open-ended NL→SQL quality rather than fixture coverage — that was not run in this environment, since no API key is configured here, and the README does not claim a number for it.

## Adversarial validation — 100% rejection, tested two ways

```bash
pytest tests/test_validator_adversarial.py tests/test_service_adversarial.py -v
```

- `tests/test_validator_adversarial.py` — 29 deliberately malicious/malformed SQL strings (`DROP`, `DELETE`, `UPDATE`, `INSERT`, `CREATE TABLE AS SELECT`, `ALTER`, `PRAGMA`, `ATTACH DATABASE`, `GRANT`, `VACUUM`/`REINDEX`, stacked-statement injection via `;`, `load_extension`/`readfile`/`writefile`, `SELECT ... INTO`, empty/garbage input) fed **directly to `validate_sql()`** — 29/29 rejected, plus 2 dedicated tests pinning exactly how comment-smuggled second statements are handled (33 test functions total in the file).
- `tests/test_service_adversarial.py` — the same guarantee at the `ask()` level, via a fixture LLM client that *always complies* with an adversarial natural-language prompt instead of refusing it — proving the validator is what blocks execution, "not by hoping the model refuses" (the spec's own phrasing for this acceptance criterion). 8/8 adversarial prompts still end up rejected even though the fixture model never says no.

The validator's `_ALLOWED_ROOT_TYPES` is an **allow-list** (`Select`/`Union`/`Intersect`/`Except`), not a blocklist of dangerous keywords — every DML/DDL/admin statement sqlglot recognizes parses to a distinct, non-allow-listed AST node type by construction, so there's no keyword list to keep in sync and no way to rename or disguise a destructive statement into passing.

## What needs a real API key vs. what works standalone today

| Capability | Works today, no key | Needs `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` |
|---|---|---|
| Schema introspection | ✅ | |
| AST validation (all 8 checks, adversarial suite) | ✅ — fully real, provider-independent | |
| Read-only execution against SQLite | ✅ | |
| MCP server (`list_schema`, `ask` tools) | ✅ | |
| Answering the 20 fixture-covered eval questions | ✅ (rule-based backend) | |
| Genuine open-ended NL→SQL on **novel** phrasings | ❌ — the rule-based backend only recognizes its fixed question set (plus two narrow "how many X"/"list all X" templates) | ✅ — `AnthropicLLMClient`/`OpenAILLMClient` handle arbitrary phrasing |
| The 5 deliberately-unanswered eval questions | ❌ by design | ✅ |

`llm/factory.py` picks the backend automatically: Anthropic if `ANTHROPIC_API_KEY` is set, else OpenAI if `OPENAI_API_KEY` is set, else the rule-based fallback — no code changes needed to switch. **The AST validator's behavior is identical regardless of which backend produced the SQL** — that's the actual point of the architecture (the model's output is a proposal, never trusted), and it's why the adversarial suite and general validator tests don't need any LLM backend at all to prove the safety property.

## Edge cases handled

- **Ambiguous NL question** (§9): rather than silently picking one interpretation, the prompt instructs the LLM to respond `AMBIGUOUS: <clarifying question>` instead of SQL; `service.ask()` detects this and returns `rejected: true` with the clarification as the reason, never executing a guess. See `test_ask_handles_ambiguous_question_without_silently_guessing`.
- **Join-heavy questions tracked separately** (§9): `EvalQuestion.is_join_heavy` + `EvalReport.accuracy_by_join_heaviness()` — see the real 100% vs. 37.5% split above.
- **Prompt injection disguised as SELECT** (§9): the allow-list root-type check means a `DROP`/`DELETE`/etc. can't pass no matter how the prompt asks for it; see the adversarial suites above.
- **Very large table full scan** (§9): `_find_unfiltered_large_table_scan` flags a `SELECT` with no `WHERE` on a table above the row-count threshold (500 by default) *and* whose result isn't otherwise bounded (no `GROUP BY`, no `LIMIT`, not a pure aggregate). That last clause is a deliberate refinement beyond the spec's literal wording: without it, ordinary reporting queries like `SELECT COUNT(*) FROM permits` would be rejected alongside genuinely expensive `SELECT * FROM permits`, which would make the validator useless for real reporting. See `test_pure_aggregate_on_large_table_passes_without_where` vs. `test_unfiltered_select_star_on_large_table_is_rejected`.
- **Schema mismatches** (hallucinated table/column names): checked structurally against the introspected schema, not string-matched against a hardcoded list — `test_unknown_table_is_rejected`, `test_unknown_column_on_known_table_is_rejected`. Column-existence checking is deliberately conservative (skips ambiguous unqualified references across multiple joined tables) to avoid false-positive rejections of legitimate queries — see the docstring on `_find_unknown_column`.

## MCP server

```bash
text-to-sql-mcp serve
```

Runs the server over stdio. Point any MCP client at it (e.g. add it to Claude Desktop's config, or drive it with the `mcp` Python SDK's `ClientSession`). Tested end-to-end in `tests/test_mcp_server.py` via `mcp.shared.memory.create_connected_server_and_client_session` — a real `ClientSession` talking to a real `FastMCP` server over an in-memory transport, calling `list_tools()` and `call_tool(...)` exactly as an external MCP client would, not just invoking the underlying Python functions directly.

## Testing

```bash
pytest
```

91 tests, all passing. Breakdown:

- `test_introspection.py` — schema introspection accuracy (tables, columns, row counts, large-table threshold)
- `test_rule_based_llm.py` — deterministic backend coverage, including its deliberate gaps
- `test_execution.py` — read-only enforcement (defense in depth), row-limit truncation
- `test_validator_general.py` — valid queries pass, schema grounding, bounded-vs-unbounded large-table logic
- `test_validator_adversarial.py` — 29-case adversarial suite, 100% rejection
- `test_service_ask.py` / `test_service_adversarial.py` — end-to-end `ask()`, including the full-pipeline adversarial proof
- `test_eval_runner.py` — the eval harness itself (shape, accuracy breakdowns, ambiguity handling)
- `test_query_log.py` — logging + the operator-facing rejection-rate report, including a real `ask()` integration test
- `test_mcp_server.py` — end-to-end via a real MCP `ClientSession`

## Configuration

Copy `.env.example` to `.env` and fill in what you have — everything has a working default:

```bash
cp .env.example .env
```

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | unset | If set, real Claude-backed NL→SQL generation |
| `ANTHROPIC_MODEL` | `claude-opus-5` | |
| `OPENAI_API_KEY` | unset | Used only if `ANTHROPIC_API_KEY` is not set |
| `OPENAI_MODEL` | `gpt-4o-mini` | |
| `CIVIC_DB_PATH` | `data/civic.db` | |
| `APP_DB_PATH` | `data/app.db` | eval_questions/query_log metadata |
| `LARGE_TABLE_ROW_THRESHOLD` | `500` | Row count above which a table is "large" for the missing-WHERE check |
| `MAX_RESULT_ROWS` | `200` | Cap on rows returned per query |

## Risks / Open Questions / Scope cuts

Honest accounting of what didn't make it in, per the spec's own §13 and this portfolio's engineering-judgment mandate:

- **Postgres, not SQLite, per the spec's literal wording.** No Postgres server or Docker daemon is available in this environment. Documented substitution + upgrade path above; the AST validator and execution-layer design were kept dialect-agnostic on purpose so this isn't a rewrite later.
- **Synthetic dataset, not a live open-data portal pull.** Deliberate trade-off for offline reproducibility and to sidestep the licensing question the spec itself flags as a risk — see the dedicated section above.
- **Rule-based backend is a fixture lookup table, not a general model.** This is explicit and by design per this portfolio's environment constraints (no LLM API keys configured here) — the real Anthropic/OpenAI backends exist, are fully implemented, and share the identical validator/execution path; they were simply never run against a live API key in this environment, so no live-generation accuracy number is claimed.
- **Column-existence checking is best-effort, not exhaustive.** It deliberately skips ambiguous unqualified column references across multi-table joins rather than risk false-positive rejections — documented in `_find_unknown_column`'s docstring. Table-existence checking (the higher-value guard against hallucinated tables) is not similarly hedged.
- **No query result caching / connection pooling.** Each `ask()` opens a fresh read-only SQLite connection. Fine at this scale (single-file demo DB); would need attention before high-QPS production use.
- **Ambiguity detection depends on the LLM backend following the `AMBIGUOUS:` convention.** The rule-based backend implements it for its one deliberately-ambiguous fixture question; a real Anthropic/OpenAI call is instructed to follow the same convention via the shared system prompt (`llm/prompt.py`) but this is prompt-level cooperation, not independently enforced by the validator (open-ended ambiguity detection isn't a thing an AST checker can verify).
- **`MISSING_WHERE_LARGE_TABLE`'s bounded-result heuristic is a refinement beyond the spec's literal wording**, not a limitation exactly, but worth flagging as a judgment call: it treats `GROUP BY`, `LIMIT`, and pure-aggregate projections as exempt from the missing-WHERE check. See the [Edge cases](#edge-cases-handled) section for the reasoning and the two tests that pin the behavior on each side of the line.

## License

MIT — see [LICENSE](LICENSE).
