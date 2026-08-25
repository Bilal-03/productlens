# Question Taxonomy

Supported intents: `kpi`, `trend`, `comparison`, `ranking`, `segmentation`, `funnel`, `retention`, `cohort`, `feature_adoption`, `revenue`, `acquisition`, and `diagnostic`.

Material ambiguity returns clarification. “Show conversion,” for example, offers visitor-to-signup, signup-to-activation, trial-to-paid, and checkout-to-payment rather than silently choosing.

Unsupported or unsafe requests return stable error codes and safe explanations.

Questions outside the governed metric templates can use the structured ad-hoc
SQL path. That path receives only relevant PII-free analytics schema context,
uses one read-only `SELECT` contract, and gets at most one repair for syntax or
allowlisted-schema errors. Unsafe SQL is rejected without repair.
