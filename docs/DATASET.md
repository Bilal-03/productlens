# Synthetic Dataset

The generator creates users, sessions, events, subscriptions, and transactions over at least 180 days. The portfolio profile targets 20K users, 120K sessions, 500K–650K events, 12K subscriptions, and 25K transactions while remaining below the Supabase free database ceiling.

The seed is `20260824`; data ends at 2026-08-23 UTC. Relative dates resolve against this metadata instead of wall-clock time, making demo questions reproducible.

The dataset contains no real personal information. Country, channel, device, browser, plan, company size, and campaign are governed dimensions.

Run `DATABASE_ADMIN_URL=... backend/.venv/bin/python -m app.data.generate --profile full --load` to load and validate. The loader checks all documented scenario directions from generated rows and fails the load if a full-profile gate is not met. Scenario checks use set-based event flags and a bounded 120-second administration timeout so the full seed remains viable on small Supabase compute tiers. If loading has already committed and only validation needs to be retried, run `make seed-validate`; it does not regenerate or overwrite data. The smoke profile uses the same checks, with D30 acquisition-retention direction reported as sample-sensitive rather than treated as a full-profile acceptance gate.
