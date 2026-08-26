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
