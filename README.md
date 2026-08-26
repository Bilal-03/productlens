# ProductLens AI

ProductLens AI is an AI-assisted product analytics workspace that turns natural-language business questions into validated analytical investigations. It combines a governed semantic metrics layer, AST-validated read-only SQL, deterministic product analytics, controlled visualizations, and evidence-backed recommendations.

> Current status: P0/P1 parity is implemented and validated locally. The remaining rollout steps are credential-gated production migration/reseed, deployment smoke checks, and screenshot capture; explicit P2/P3 non-goals remain deferred. See [Implementation Status](docs/IMPLEMENTATION_STATUS.md) for the evidence matrix.

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
- A reproducible synthetic dataset with known diagnostic scenarios

## Local setup

Prerequisites: Docker, Node 22.x, npm 10+, and Python 3.12+.

1. Copy `.env.example` to `.env` and optionally add Gemini/Groq keys.
2. Run `make db`.
3. Create `backend/.venv`, install the backend package, and run `make migrate` (the administration URL is the `migration_owner` role).
4. Run `make seed-smoke` for development or `make seed` for the portfolio-scale dataset.
5. Start FastAPI from `backend/` with `uvicorn app.main:app --reload`.
6. Install frontend dependencies and run `npm run dev` from `frontend/`.
7. Run `make preflight` after a production frontend build to verify deployment entry points, environment placeholders, and artifact-size limits.

The dataset is synthetic and anchored to 2026-08-24 so relative-period demo questions remain reproducible.

Validation gates currently include 262 fast backend tests plus five opt-in PostgreSQL API integration tests (267 when enabled in CI), a 58/58 offline planner/table/chart benchmark, 160 adversarial SQL-safety cases, frontend lint/typecheck/Vitest/build, deployment preflight, and eleven passing desktop/mobile Playwright flows (one desktop-only skip for the mobile navigation check). The full deterministic profile produces 20,000 users, 120,000 sessions, 624,021 events, 12,000 subscriptions, and 25,000 transactions; the deployed database must still be checked against the documented 450 MB ceiling.

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
