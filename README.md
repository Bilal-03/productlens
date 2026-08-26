# ProductLens AI

ProductLens AI is an AI-assisted product analytics workspace that turns natural-language business questions into validated analytical investigations. It combines a governed semantic metrics layer, AST-validated read-only SQL, deterministic product analytics, controlled visualizations, and evidence-backed recommendations.

> Current status: P0/P1 parity, P2 proactive analytics, Phases 39–40, and Phase 43 are implemented. The bounded P3 milestone is now implemented end to end: optional Supabase Auth/OIDC with verified JWKS bearer tokens, group-to-role mapping, server-side tenant source routing, a read-only PostgreSQL connector, reconnectable SSE updates, and a typed three-stage Copilot orchestration. The anonymous demo remains available. Protected tenant workspaces still require the deployment environment and identity-provider claims described in [Deployment](docs/DEPLOYMENT.md), followed by the integration/live smoke checklist. See [Implementation Status](docs/IMPLEMENTATION_STATUS.md) for the evidence matrix.

## Why it exists

Product teams often depend on analysts to translate business questions into SQL and manually investigate results. ProductLens reduces that workflow to:

`Question → Plan → Metric → Safe SQL → Analysis → Evidence → Decision → Action`

It is deliberately not a generic chatbot or unrestricted text-to-SQL wrapper.

## Core capabilities

- Governed KPI, funnel, cohort, retention, segmentation, feature-adoption, and revenue analytics
- Structured Quick Answer and Deep Dive investigations
- SQLGlot AST validation plus an independent read-only PostgreSQL role
- Deterministic comparisons and contribution analysis
- Gemini-first, Groq-fallback provider abstraction with deterministic degradation
- Structured ad-hoc text-to-SQL with semantic schema retrieval and one safe repair attempt
- Query transparency, anonymous-session history, audit logs, and confidence/caveats
- Provider-neutral signed workspace access context with viewer/analyst/admin permissions
- Configured OIDC/JWKS bearer validation with issuer, audience, expiry, key-rotation, and group-role checks
- Optional Supabase Auth email/password sign-in, refresh, logout, and anonymous fallback
- Server-side workspace-to-source routing with tenant-isolated history, cache, reports, and Copilot execution
- Read-only PostgreSQL connector with governed view/column contract, health checks, timeouts, and dataset fingerprints
- Fast first-paint and refresh path with a critical KPI summary, deferred overview details, bounded tenant/source engine reuse, short-lived fingerprints, in-process result reuse, a daily-activity MAU rollup, and grouped 90-day trends
- Bounded SSE analytics snapshots with heartbeats, event IDs, fingerprint updates, and automatic browser reconnects
- Typed Planner → Analyst → Evidence Copilot orchestration with fixed capabilities and deterministic fallback
- Explainable anomaly detection, Product Pulse, deterministic weekly reports, and Markdown export
- Governed experiment comparisons plus deterministic churn-risk, journey, stickiness, power-user, and observed revenue-cohort analytics (Phase 39–40 first slice)
- Session-scoped Analysis Notebook for pinning, reopening, and summarizing validated investigations (Phase 43)
- A reproducible synthetic dataset with known diagnostic scenarios

## Local setup

Prerequisites: Docker, Node 22.x, npm 10+, and Python 3.12+.

1. Copy `.env.example` to `.env` and optionally add Gemini/Groq keys.
2. Run `make db`.
3. Create `backend/.venv`, install the backend package, and run `make migrate` (the administration URL is the `migration_owner` role; this applies the daily activity rollup used by advanced stickiness).
4. Run `make seed-smoke` for development or `make seed` for the portfolio-scale dataset.
5. Start FastAPI from `backend/` with `uvicorn app.main:app --reload`.
6. Install frontend dependencies and run `npm run dev` from `frontend/`.
7. Run `make preflight` after a production frontend build to verify deployment entry points, environment placeholders, and artifact-size limits.

The dataset is synthetic and anchored to 2026-08-24 so relative-period demo questions remain reproducible.

Validation gates include the existing offline planner/table/chart benchmark, adversarial SQL-safety corpus, frontend lint/typecheck/Vitest/build, deployment preflight, and desktop/mobile Playwright flows. The P2 unit and contract gates cover governed daily series, anomaly policy, caching, typed report APIs, Markdown export, and Product Pulse/report components. Phase 39–40 gates additionally cover experiment assignment semantics, uplift/significance guards, advanced query allowlists, UTC daily-activity rollup semantics, cache invalidation, partial-result contracts, API/UI surfaces, and opt-in PostgreSQL execution. Phase 43 gates cover session scoping, idempotent notebook persistence, evidence-bound deterministic summary aggregation, saved-analysis projection, and responsive route/component states. P3 gates cover JWT claims/signature/key rotation, RBAC precedence, server-only source routing and isolation, connector contract/read-only behavior, bounded SSE framing/reconnects, and typed orchestration fallback/capabilities. The full deterministic profile produces 20,000 users, 120,000 sessions, 624,021 events, 12,000 subscriptions, and 25,000 transactions; production was measured at 199 MB against the documented 450 MB ceiling. Local PostgreSQL-backed tests remain opt-in when a database is unavailable; production activation of protected tenants requires the deployment checklist.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Metrics](docs/METRICS.md)
- [Dataset](docs/DATASET.md)
- [Synthetic scenarios](docs/SYNTHETIC_SCENARIOS.md)
- [Security](docs/SECURITY.md)
- [Evaluation](docs/EVALUATION.md)
- [Case study](docs/CASE_STUDY.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Implementation status](docs/IMPLEMENTATION_STATUS.md)

## Scope and claims

This is a public portfolio application using synthetic data. It demonstrates read-only execution, AST validation, deterministic analytics, and benchmark evaluation. It does not claim enterprise readiness, causal inference from observational data, or perfect LLM accuracy.
