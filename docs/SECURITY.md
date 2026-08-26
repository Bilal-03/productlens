# Security Model

- Synthetic data only; no public database client or privileged frontend credentials.
- Generated SQL is parsed as PostgreSQL with SQLGlot and must be one read-only query.
- Ad-hoc structured SQL is validated before execution; only syntax/schema failures get one repair attempt, while unsafe SQL is rejected without repair.
- Only explicit, PII-free analytics views and columns are available. Migration `0002_p0p1_completion` revokes broad analytics access and grants `analytics_reader` the five core views; migration `0003_experiments_advanced_analytics` adds only the named experiment metadata and assignment views (`analytics.experiments` and `analytics.experiment_assignments`).
- DDL, DML, system catalogs, comments, cross joins, locking, unsafe functions, and excessive complexity are rejected.
- A 5,000-row cap and five-second statement timeout constrain resource use.
- PostgreSQL permissions independently enforce read-only access.
- Anonymous session identifiers are HMAC-hashed; raw IP addresses are not stored.
- Notebook saves accept only a source query ID, then re-read and validate the session-owned history record server-side before storing a snapshot in `operational.saved_insights`.
- Per-session and global AI quotas protect free provider keys.
- Deterministic KPI/funnel responses are cached by dataset version; cache writes stay in the operational schema and never bypass the analytics read boundary.
- Lifecycle, feature, transaction-type, failure-reason, experiment-assignment, and experiment-status indexes support the governed investigations without widening the read boundary.
- Every generation, validation, repair attempt, execution, and failure is audited without exposing credentials. Provider/model and token counts are stored as operational metadata; prompts, API keys, and raw model responses are not stored.

## P3 workspace access boundary

- The API accepts an optional provider-neutral `X-ProductLens-Access` assertion. The current `plx1` format is a compact, three-part HMAC-SHA256 token containing only a workspace ID, subject ID, role, issue time, and expiry. There is no public token-minting endpoint; issuance belongs to a trusted SSO provider or deployment gateway.
- The API also accepts `Authorization: Bearer <JWT>` when OIDC is configured. The verifier uses only deployment-configured JWKS and asymmetric algorithms (`RS256/384/512`, `ES256/384/512`), requires `iss`, `aud`, `sub`, and `exp`, and validates issuer, audience, signature, and expiry before reading custom workspace/group claims. The cached JWKS client refreshes for a new `kid`, supporting normal signing-key rotation without trusting a request-supplied key URL.
- OIDC groups map through the exact `OIDC_ROLE_GROUPS` deployment mapping. Admin, analyst, and viewer precedence is explicit; a token with no mapped group is rejected rather than receiving a default privilege.
- `viewer`, `analyst`, and `admin` roles are mapped to explicit permissions. Every analytics/read surface requires `analytics:read`; Copilot analysis and notebook writes additionally require the corresponding analyst permissions. Invalid or expired assertions return `401`; insufficient permissions return `403`.
- Signed sessions derive an HMAC session key from workspace/tenant, subject, and the caller's browser session. History, quotas, audit rows, and saved notebook state therefore cannot collide across signed workspaces even when browser session values are reused. Raw assertions and claims are not persisted.
- The anonymous demo remains an analyst-scoped compatibility path. Authenticated requests resolve the verified workspace claim through the server-only `TENANT_SOURCE_CONFIG`; clients cannot submit a tenant ID, source ID, database URL, or SQL override. Missing or malformed mappings fail closed with a protected-resource error.
- The first external connector is PostgreSQL-only. It validates the fixed semantic view/column contract, uses read-only transactions and statement timeouts, runs no user-supplied SQL, and fingerprints the source dataset for cache invalidation. Operational history, notebook state, quotas, reports, Copilot execution, and result-cache namespaces include the verified tenant/source boundary.
- `GET /api/v1/stream/analytics` requires the same `analytics:read` authorization, accepts `Last-Event-ID` only as a reconnect cursor, never accepts tokens in query parameters, emits bounded snapshots/heartbeats, and closes so the browser can reconnect.
- Copilot orchestration is fixed to Planner, Analyst, and Evidence stages. Capabilities are hard-coded, handoffs are typed metadata only, and provider failure/timeout falls back to deterministic evidence. Hidden reasoning is not returned or persisted.
- `ACCESS_TOKEN_SECRET` must be a production-only secret distinct from `SESSION_HMAC_SECRET` and must never be exposed through `NEXT_PUBLIC_*` variables. Supabase public URL/anon key values may be exposed to the frontend; database URLs, OIDC/JWKS settings, connector credentials, HMAC secrets, and provider keys remain server-only. The auth client stores its session locally, but ProductLens sends only the access token in the `Authorization` header and never in a URL.
- OIDC deployment variables (`OIDC_ISSUER_URL`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL`, `OIDC_WORKSPACE_CLAIM`, `OIDC_GROUPS_CLAIM`, and `OIDC_ROLE_GROUPS`) plus `TENANT_SOURCE_CONFIG` and connector URL variables are server-only. Supabase custom access-token claims must provide top-level `workspace_id` and `groups`; a token without a mapped role or tenant source is rejected/fails closed.

The regression corpus currently contains 160 unsafe cases (including destructive SQL, injection, comments, multi-statements, system catalogs, unknown identifiers, cross joins, locking, unsafe functions, non-deterministic functions, and unbounded queries) plus safe set-operation/CTE controls.

This is defense in depth for a portfolio demo, not a claim of complete or enterprise security.
