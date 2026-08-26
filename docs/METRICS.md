# Governed Metrics

Metric definitions live in one validated registry. Rates specify their entity, numerator, denominator, valid dimensions, and display format. Relative change and percentage-point change are always reported separately.

- Active users: distinct users performing qualifying product activity in the period.
- Visitors: distinct sessions with `landing_page_viewed` in the period.
- Signups: distinct users with `signup_completed` in the period.
- Activated users: signed-up users completing onboarding within seven days of signup.
- Paid users: users with a successful paid transaction or an active paid subscription at period end.
- Channel conversion: signups divided by visitors; acquisition breakdowns report the same numerator and denominator per governed segment.
- Signup conversion: landing sessions that reach signup completion.
- Activation: signed-up users completing onboarding within seven days.
- Checkout conversion: checkout sessions reaching successful payment.
- Payment success: successful payment attempts divided by submitted attempts.
- Payment failures: distinct checkout sessions with a `payment_failed` event. This is a count metric, not a failure-rate estimate.
- MRR: active recurring value normalized monthly at period end; ARR is twelve times MRR.
- Revenue: successful charges and renewals less refunds.
- Churn: cancellations in period divided by subscriptions active at period start.
- Retention: cohort members with qualifying activity in the requested return window.
- Weekly retention: activity during days 7–13 after signup (the D7–D13 window).
- Monthly retention: activity during days 30–59 after signup (the D30–D59 window).
- A weekly/monthly cohort is immature until the full return window is observable; immature values are `null`, never zero.
- Feature adoption: active eligible users using the feature divided by eligible active users.

Diagnostic dimensions are derived, governed views rather than free-form SQL fields:

- `customer_type`: New Customer for `charge`, Returning Customer for `renewal` or `refund`.
- `revenue_motion`: `charge`, `renewal`, or `refund`.
- `failure_reason`: the recorded payment/renewal failure reason, or `none` for successful transactions.

All timestamps use UTC and the period end is exclusive. `MRR` is active subscription value at period end, `ARR` is `12 × MRR`, and revenue is successful charges/renewals minus refunds. Feature-retention differences are observational associations, not causal effects.

Association results must use “associated with,” “correlated with,” or “observed among”; they must not imply causation.

## Proactive analytics policy

Anomaly detection compiles governed daily UTC series for revenue, signups, activation, checkout conversion, payment success, payment failures, churn, and DAU. It evaluates a 90-day analysis horizon with a 28-day trailing baseline, requires at least 14 baseline observations and a 100-entity sample, and flags movement only when both the z-score and metric-specific relative-change thresholds are crossed. Consecutive same-direction flags are collapsed into explainable episodes with warning or critical severity. Product Pulse uses fixed diagnostic dimensions from the registry; it never accepts arbitrary dimensions or user-supplied SQL.

Weekly report metrics are deterministic and cached on demand by request, policy version, and dataset version. An optional single grounded provider interpretation may refine report prose only; provider failure or grounding rejection returns deterministic wording. Retention values remain unavailable for immature cohorts rather than being treated as zero.
