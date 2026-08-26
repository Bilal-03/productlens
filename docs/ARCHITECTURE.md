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

## Experiment and advanced analytics

```text
Experiment metadata + user assignments → governed cohort compiler
                                      → read-only SQL → conversion outcomes
                                      → uplift / confidence interval / significance guardrails
                                      → experiment analysis UI

Governed events + subscriptions + transactions → bounded concurrent queries
                                                → churn-risk signals / journeys
                                                → stickiness / power users / revenue cohorts
                                                → typed advanced analytics UI
```

Phase 39 uses explicit `experiments` and `experiment_assignments` views. The API accepts only a known experiment key, period, and primary metric from the catalog; it never accepts experiment SQL or arbitrary dimensions. Activation uses assigned users who completed signup, while checkout and payment-success analyses use assigned sessions with their governed eligibility event. Results include sample sizes, absolute/relative uplift, a two-sided two-proportion test, and a minimum-sample warning.

The first Phase 40 slice is descriptive rather than predictive. Churn risk is a transparent band derived from observed cancellation and recent qualifying activity by fixed dimensions; journeys use a fixed event vocabulary and five-step cap; stickiness uses daily active users, trailing seven-/thirty-day populations, and a ten-active-day power-user definition; revenue cohorts expose observed net revenue per signed-up user and mark cohorts immature until thirty days are observable. All query shapes pass the same SQLGlot and read-only boundary, and responses use the existing dataset-version result cache. Migration `0003_experiments_advanced` and a deterministic reseed put the experiment/advanced tables and data in production; `0004_advanced_perf` refreshes the event access path and statistics for the default 90-day advanced request.

## Analysis notebook

```text
Copilot result → session-authenticated source query ID → history ownership check
              → validated analysis snapshot → saved_insights → notebook board
              → reopen source evidence / remove saved item
```

Phase 43’s first slice stores a server-side snapshot of a validated `AnalysisResponse`. The client never posts arbitrary evidence or SQL: it submits only the source query ID, and the API hashes the anonymous session before reading history. The unique `(session_hash, source_query_id)` key makes saves idempotent; the `app_writer` role can manage only the operational notebook table. Executive summaries over a saved board remain a later slice.

## Boundaries

- `frontend`: presentation, interaction, controlled Plotly rendering.
- `api`: validation and orchestration only.
- `semantic`: governed metrics, dimensions, schema metadata, time semantics.
- `analytics`: deterministic calculations and query compilers.
- `ai`: provider adapters, planner, SQL generation, grounded interpretation.
- `security`: AST validation, quotas, session hashing, grounding validation.
- `database`: connection roles, execution, history, audit, and cache.
- `notebook`: session-scoped saved-analysis persistence and typed notebook projections.

## Runtime roles

Generated analysis uses `analytics_reader`, which has `SELECT` on approved `analytics` views only. Operational writes use `app_writer`. Migrations and seeding use `migration_owner`; those credentials are never available to the frontend or ordinary analysis requests.
