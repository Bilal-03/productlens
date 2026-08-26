# Evaluation

Evaluation separates deterministic correctness from model variability.

- Unit fixtures validate metrics, periods, funnels, retention, and contribution arithmetic exactly.
- The safety corpus must reject every destructive, injected, multi-statement, system-table, and unbounded query.
- A curated benchmark stores expected intent, metric, dimensions, tables, chart type, and approximate answer for 58 questions spanning every supported P0/P1 category.
- With `--with-database`, governed current-period queries are executed against the configured database and finite numerical results are recorded; this is a smoke correctness check, not a substitute for exact fixture assertions.
- Live provider evaluation is optional and emits timestamped results with the provider/model named.
- README metrics are published only after a real evaluation run.

The current offline benchmark is 58/58 (`make benchmark`). It checks planner intent/metric/dimensions, compiler table coverage, and controlled chart inference. `make benchmark` intentionally does not claim a live-provider score; provider evaluations must be timestamped separately with the actual model and measured results.

On the clean full-profile local PostgreSQL fixture, uncached acquisition, feature-adoption, retention, and overview calls completed in approximately 442 ms, 1.50 s, 882 ms, and 3.18 s respectively; the cached overview repeated in 3 ms. These are engineering checks on the fixture hardware, not an SLA for Supabase or Vercel.
