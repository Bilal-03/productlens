# Architecture

## Pipeline

```text
Question → Classification → Analytics plan → Metric resolution → Schema resolution
         → SQL generation → SQL AST validation → Read-only execution
         → Deterministic analysis → Driver analysis → Visualization
         → Evidence-backed interpretation → Recommendation → Follow-up
```

The LLM parses and interprets; it does not calculate metrics or control credentials. Governed analytics compile through trusted SQL builders. Supported ad-hoc questions use a structured SQL contract with relevant semantic schema retrieval, then pass through the identical SQLGlot validator and read-only executor. Syntax/schema failures receive exactly one repair attempt; unsafe SQL is rejected without repair.

## Boundaries

- `frontend`: presentation, interaction, controlled Plotly rendering.
- `api`: validation and orchestration only.
- `semantic`: governed metrics, dimensions, schema metadata, time semantics.
- `analytics`: deterministic calculations and query compilers.
- `ai`: provider adapters, planner, SQL generation, grounded interpretation.
- `security`: AST validation, quotas, session hashing, grounding validation.
- `database`: connection roles, execution, history, audit, and cache.

## Runtime roles

Generated analysis uses `analytics_reader`, which has `SELECT` on approved `analytics` views only. Operational writes use `app_writer`. Migrations and seeding use `migration_owner`; those credentials are never available to the frontend or ordinary analysis requests.
