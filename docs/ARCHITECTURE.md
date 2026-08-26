# Architecture

## Pipeline

```text
Question → Classification → Analytics plan → Metric resolution → Schema resolution
         → SQL generation → SQL AST validation → Read-only execution
         → Deterministic analysis → Driver analysis → Visualization
         → Evidence-backed interpretation → Recommendation → Follow-up
```

The LLM parses and interprets; it does not calculate metrics or control credentials. Governed analytics compile through trusted SQL builders. Supported ad-hoc questions use a structured SQL contract with relevant semantic schema retrieval, then pass through the identical SQLGlot validator and read-only executor. Syntax/schema failures receive exactly one repair attempt; unsafe SQL is rejected without repair.

## Proactive analytics

```text
Dataset version → bounded daily governed series → SQLGlot validation
               → read-only execution → rolling baseline/z-score gates
               → collapsed anomaly episodes → fixed-dimension drivers
               → Product Pulse / weekly report → optional grounded prose
```

The proactive endpoints are on-demand; no scheduler or schema migration is required for this milestone. Series compilation is allowlisted to the eight P2 metrics and capped at 118 days (90 analysis days plus 28 baseline days). Each statement is validated and executed through `analytics_reader`. Independent series, driver, and report-metric queries use bounded concurrency so the request is not dominated by serial round trips. Complete response payloads are stored in `operational.result_cache` with request and policy-version keys plus the dataset version supplied to the cache lookup, so reseeding invalidates stale results. Report values, anomaly calculations, drivers, recommendations, and Markdown rendering remain deterministic. A single optional provider call may refine report prose, but it has a short timeout and one attempt; the grounded-insight validator falls back to deterministic text if it is unavailable or introduces unsupported evidence/numbers. The report also has an internal response budget below the Vercel function limit and returns partial sections with warnings when an optional input cannot fit within that budget.

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
