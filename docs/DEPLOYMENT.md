# Deployment

Deploy the monorepo as two Vercel projects: `frontend/` for Next.js and `backend/` for FastAPI. Both use environment variables; `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SUPABASE_URL`, and `NEXT_PUBLIC_SUPABASE_ANON_KEY` are the only frontend-visible values. Supabase hosts PostgreSQL and can also provide the optional Auth/OIDC session.

Run migrations and deterministic seeding from a trusted local or CI administration job. Never migrate or seed during an HTTP request or serverless startup. The GitHub Actions backend job bootstraps the local role boundary, runs the Alembic migration, loads the smoke profile, and enables `RUN_DB_INTEGRATION=1` for real PostgreSQL API coverage.

Before deployment, verify the backend bundle is below Vercel's Python limit and the database remains below 450 MB. Configure exact CORS origins, the migration-owner administration URL, both runtime database roles, provider keys, the session HMAC secret, the separate access-token HMAC secret, optional OIDC issuer/audience/JWKS/group mappings, quotas, cache TTL, and timeouts.

Run `make preflight` after the frontend production build. The dependency-free gate checks both Vercel entry points, the required environment contract, standalone frontend output, and the local backend/frontend artifact sizes. Vercel remains the authoritative check for the final dependency bundle.

## External deployment handoff

1. In Supabase, click **Connect** and copy a direct connection string for administration/migrations. Supabase documents direct port `5432` as the option for migrations; use the session pooler on port `5432` instead if your network is IPv4-only. Keep the password private. ([Connection guidance](https://supabase.com/docs/guides/database/connecting-to-postgres))
2. Set `DATABASE_SUPERUSER_URL`, `MIGRATION_OWNER_PASSWORD`, `APP_WRITER_PASSWORD`, and `ANALYTICS_READER_PASSWORD` in a local shell, then run `make bootstrap-roles`. The command creates the three least-privilege roles without storing their passwords in the repository.
3. Replace the role URLs in your local environment with the Supabase host, database, and corresponding role passwords. Run `make migrate` (including migrations `0002_p0p1_completion`, `0003_experiments_advanced`, `0004_advanced_perf`, `0005_analysis_notebook`, and `0006_daily_activity`), then `make seed` for a fresh deterministic load. Migration `0006_daily_activity` backfills the existing events in UTC, so a reseed is not required solely for this migration. Confirm the generated database remains below 450 MB and that the analytics-reader role can select approved views only.
### High-Performance Deployment (Render Backend + Vercel Frontend)

1. **Deploy Backend to Render**:
   - In [Render Dashboard](https://dashboard.render.com), click **New +** -> **Web Service** (or use the Blueprint from `render.yaml`).
   - Connect the repository and set:
     - **Root Directory**: `backend`
     - **Runtime**: `Python`
     - **Build Command**: `pip install --upgrade pip && pip install -e .`
     - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2 --timeout-keep-alive 65`
     - **Health Check Path**: `/api/v1/health`
   - Set Environment Variables:
     - `ENVIRONMENT=production`
     - `DB_POOL_CLASS=queue`
     - `DB_POOL_SIZE=10`
     - `DB_MAX_OVERFLOW=5`
     - `DB_POOL_RECYCLE_SECONDS=1800`
     - `APP_DATABASE_URL=<your-supabase-connection-string>`
     - `ANALYTICS_DATABASE_URL=<your-supabase-connection-string>`
     - `FRONTEND_ORIGIN=https://<your-frontend-domain>.vercel.app`
     - `SESSION_HMAC_SECRET=<secret>`
     - `ACCESS_TOKEN_SECRET=<secret>`
     - `GEMINI_API_KEY=<key>` (and/or `GROQ_API_KEY`)

2. **Deploy Frontend to Vercel**:
   - Create a Vercel project rooted at `frontend/`.
   - Set `BACKEND_INTERNAL_URL=https://<your-render-service>.onrender.com/api/v1` (or `NEXT_PUBLIC_API_URL`).
   - Next.js will automatically proxy `/api/v1/:path*` to the persistent Render instance, eliminating CORS preflight `OPTIONS` latency and avoiding serverless Python cold starts.

3. **Alternative: Serverless Vercel Dual Deploy**:
   - Deploy `backend/` to Vercel via `backend/vercel.json` and `frontend/` to Vercel with `NEXT_PUBLIC_API_URL` pointing to the backend function. Note: Ephemeral Python serverless functions incur cold start latency.

## Current production verification

The current deployment completed the initial checklist on 2026-08-26. The Supabase full-profile database is 199 MB; dataset metadata reports 20,000 users, 120,000 sessions, 624,021 events, 12,000 subscriptions, and 25,000 transactions. The production smoke also verifies cumulative onboarding stages (no stage conversion above 100% or negative drop-off), 56.8% weekly and 88.8% monthly retention cards, the flagship Deep Dive’s evidence-backed Mobile / Safari / Paid Social observation, Product Pulse, the weekly report, the onboarding experiment, and bounded advanced analytics. The Markdown endpoint returned HTTP 200 with `text/markdown` and an attachment filename; repeated report loads were served from the result cache. Screenshots are stored in [`docs/screenshots/`](screenshots/).

Phase 39 is live and was verified after migration `0003_experiments_advanced` and the full reseed. Phase 40 is live through the default 90-day advanced-analytics surface after migration `0006_daily_activity`; the live check shows populated stickiness rows with no partial-results warning. Migration `0005_analysis_notebook` enables Phase 43 saved analyses and deterministic executive summaries; the live notebook check generated a non-empty summary from two saved snapshots on 2026-08-26. Neither `0005` nor `0006` requires a reseed when applied to the existing dataset.

The six P3 capabilities are implemented in the repository and covered by local tests. A deployment is considered P3-live only after the Supabase Auth claims, OIDC/JWKS settings, server-only tenant registry, read-only connector URL, and frontend public Auth variables are configured, then the authenticated connector, tenant-isolation, SSE reconnect, and Copilot-trace smoke checks in step 8 pass. The existing anonymous production demo continues to work without those optional protected-workspace settings.

No Supabase or provider credentials are stored in this workspace. For a new project, repeat the handoff steps above; for the current project, the production URLs and evidence are recorded in [CASE_STUDY.md](CASE_STUDY.md).
