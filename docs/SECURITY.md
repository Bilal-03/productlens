# Security Model

- Synthetic data only; no public database client or privileged frontend credentials.
- Generated SQL is parsed as PostgreSQL with SQLGlot and must be one read-only query.
- Ad-hoc structured SQL is validated before execution; only syntax/schema failures get one repair attempt, while unsafe SQL is rejected without repair.
- Only explicit, PII-free analytics views and columns are available. Migration `0002_p0p1_completion` revokes broad analytics access and grants `analytics_reader` only the named views (`analytics.users`, `analytics.sessions`, `analytics.events`, `analytics.subscriptions`, and `analytics.transactions`).
- DDL, DML, system catalogs, comments, cross joins, locking, unsafe functions, and excessive complexity are rejected.
- A 5,000-row cap and five-second statement timeout constrain resource use.
- PostgreSQL permissions independently enforce read-only access.
- Anonymous session identifiers are HMAC-hashed; raw IP addresses are not stored.
- Per-session and global AI quotas protect free provider keys.
- Deterministic KPI/funnel responses are cached by dataset version; cache writes stay in the operational schema and never bypass the analytics read boundary.
- Lifecycle, feature, transaction-type, and failure-reason indexes support the governed investigations without widening the read boundary.
- Every generation, validation, repair attempt, execution, and failure is audited without exposing credentials. Provider/model and token counts are stored as operational metadata; prompts, API keys, and raw model responses are not stored.

The regression corpus currently contains 160 unsafe cases (including destructive SQL, injection, comments, multi-statements, system catalogs, unknown identifiers, cross joins, locking, unsafe functions, non-deterministic functions, and unbounded queries) plus safe set-operation/CTE controls.

This is defense in depth for a portfolio demo, not a claim of complete or enterprise security.
