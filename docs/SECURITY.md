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
- `viewer`, `analyst`, and `admin` roles are mapped to explicit permissions. Every analytics/read surface requires `analytics:read`; Copilot analysis and notebook writes additionally require the corresponding analyst permissions. Invalid or expired assertions return `401`; insufficient permissions return `403`.
- Signed sessions derive an HMAC session key from workspace, subject, and the caller's browser session. History, quotas, audit rows, and saved notebook state therefore cannot collide across signed workspaces even when browser session values are reused. Raw assertions and claims are not persisted.
- The anonymous demo remains an analyst-scoped compatibility path. This foundation does not yet isolate the synthetic analytics dataset by tenant; connector-backed datasets and enterprise identity provisioning are required before making a multi-tenant security claim.
- `ACCESS_TOKEN_SECRET` must be a production-only secret distinct from `SESSION_HMAC_SECRET` and must never be exposed through `NEXT_PUBLIC_*` variables. The frontend keeps an optional short-lived assertion in session storage only so a future SSO callback can attach it to API requests.

The regression corpus currently contains 160 unsafe cases (including destructive SQL, injection, comments, multi-statements, system catalogs, unknown identifiers, cross joins, locking, unsafe functions, non-deterministic functions, and unbounded queries) plus safe set-operation/CTE controls.

This is defense in depth for a portfolio demo, not a claim of complete or enterprise security.
