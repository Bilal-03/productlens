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

The proactive endpoints are on-demand; no scheduler is required for this milestone. Series compilation is allowlisted to the eight P2 metrics and capped at 118 days (90 analysis days plus 28 baseline days). Each statement is validated and executed through `analytics_reader`. Independent series, driver, and report-metric queries use bounded concurrency so the request is not dominated by serial round trips. Complete response payloads are stored in `operational.result_cache` with request and policy-version keys plus the dataset version supplied to the cache lookup, so reseeding invalidates stale results. Report values, anomaly calculations, drivers, recommendations, and Markdown rendering remain deterministic. A single optional provider call may refine report prose, but it has a short timeout and one attempt; the grounded-insight validator falls back to deterministic text if it is unavailable or introduces unsupported evidence/numbers. The report also has an internal response budget below the Vercel function limit and returns partial sections with warnings when an optional input cannot fit within that budget.

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

The first Phase 40 slice is descriptive rather than predictive. Churn risk is a transparent band derived from observed cancellation and recent qualifying activity by fixed dimensions; journeys use a fixed event vocabulary and five-step cap; stickiness uses a UTC daily activity rollup, daily active users, trailing seven-/thirty-day populations, and a ten-active-day power-user definition; revenue cohorts expose observed net revenue per signed-up user and mark cohorts immature until thirty days are observable. All query shapes pass the same SQLGlot and read-only boundary, and responses use the existing dataset-version result cache. Migrations through `0006_daily_activity` are applied in production; the rollup backfills and exposes the governed daily relation needed by the default 90-day stickiness request.

## Analysis notebook

```text
Copilot result → session-authenticated source query ID → history ownership check
              → validated analysis snapshot → saved_insights → notebook board
              → reopen source evidence / remove saved item → deterministic summary
```

Phase 43 stores a server-side snapshot of a validated `AnalysisResponse`. The client never posts arbitrary evidence or SQL: it submits only the source query ID, and the API hashes the anonymous session before reading history. The unique `(session_hash, source_query_id)` key makes saves idempotent; the `app_writer` role can manage only the operational notebook table. `GET /api/v1/notebook/summary` aggregates the saved snapshots in the session using deterministic, evidence-bound themes, findings, drivers, and recommendations. It does not rerun source SQL or generate new evidence, and every displayed summary item retains source insight and evidence IDs.

## P3 access boundary

```text
OIDC provider / trusted edge gateway → Bearer JWT → JWKS + issuer/audience/expiry validation
                                    → group-to-role mapping → tenant access context + RBAC
                                    → server-only source registry → read-only connector
                                    → canonical workspace session → isolated analytics/cache/history/notebook state
```

`X-ProductLens-Access` continues to carry a short-lived HMAC-signed `plx1` assertion for a trusted gateway. The API also accepts a standard `Authorization: Bearer` OIDC JWT when `OIDC_ISSUER_URL`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL`, and exact group mappings are configured. PyJWT validates an asymmetric algorithm against the deployment-configured JWKS; its cached JWKS client refreshes when a rotated key id appears, while issuer, audience, required subject, and expiry claims are verified before RBAC is applied. Group mappings use explicit admin/analyst/viewer sets with admin precedence and fail closed when a token has no mapped role. Supabase Auth supplies the optional email/password session and top-level `workspace_id`/`groups` claims; it does not bypass backend verification.

Signed operational sessions hash workspace/tenant, subject, and the browser session together, so two workspaces cannot share history or notebook state. For authenticated requests, the verified workspace is resolved through `TENANT_SOURCE_CONFIG` and the corresponding server-only URL environment variable. The request-scoped `DatabaseService` binds all governed analytics, reports, experiments, advanced analytics, Copilot execution, dataset fingerprints, and result-cache namespaces to that source. Missing source configuration fails closed; no client-provided source, tenant override, SQL, or connector credential is accepted. Anonymous requests retain the synthetic demo binding.

## P3 connector and streaming boundaries

The first connector is a read-only PostgreSQL adapter. It checks the semantic analytics view contract, runs health and fingerprint probes inside read-only transactions with a statement timeout, and passes every analytical query through the existing SQLGlot validator before execution. The connector is intentionally deployment-configured rather than user-managed: `TENANT_SOURCE_CONFIG` maps verified workspace claims to a source ID and URL environment variable. `GET /api/v1/connectors/status` reports configuration, health, contract version, and read-only state without revealing credentials.

```text
verified tenant → fixed source binding → contract/health check
                → SQL compiler → SQLGlot validator → read-only transaction
                → tenant/source dataset fingerprint → isolated result cache
```

`GET /api/v1/stream/analytics` emits a bounded initial snapshot, fingerprint-triggered updates, heartbeats, event IDs, and a `Last-Event-ID` reconnect cursor. It requires the normal authorization header and the browser reconnects after the serverless duration limit; it is not a permanent subscription or streaming ingestion system.

## P3 Copilot orchestration

```text
Planner (classify) → typed handoff → Analyst (governed operations)
                                  → typed handoff → Evidence (bound findings/prose)
```

The orchestrator permits at most these three fixed stages and exposes only status, duration, capability labels, handoff count, and fallback metadata. The Analyst can use only existing governed analytics operations; no stage can create tools, issue arbitrary SQL, or access another tenant. Provider prose is optional and grounding-checked; timeout, provider failure, or budget exhaustion returns deterministic evidence.

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
