# Synthetic Scenarios

The generator injects patterns, not final answers. Validation derives all displayed figures from generated records.

1. **Checkout incident:** beginning 2026-08-18, Mobile Safari sessions from Paid Social receive substantially more payment failures.
2. **Onboarding friction:** the `profile_completed → integration_connected` transition loses conversion after a rollout.
3. **Feature/retention association:** users who connect an integration and invite a teammate have a higher generated D30 activity probability.
4. **Revenue decline:** August SMB monthly subscriptions experience elevated churn and failed renewals.
5. **Acquisition quality:** Paid Social has high volume but weak activation/retention; Organic Search has lower volume and stronger quality.
6. **Lifecycle and revenue motion:** every subscription has a `subscription_started` event; cancellations, charges, renewals, refunds, and payment/renewal failure reasons remain separately queryable.

Acceptance validates direction, sample size, and driver ranking. It never compares against a hardcoded narrative response.

The validator reports the observed rates and MRR values in its JSON output. On the portfolio-scale seed it also requires Organic Search to exceed Paid Social on both activation and D30 retention; the smaller smoke profile reports the retention comparison but only gates the more stable activation direction.
