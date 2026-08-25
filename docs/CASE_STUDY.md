# ProductLens AI case study

## The problem

Product teams commonly have to wait for an analyst to translate a question into SQL, check the metric definition, investigate the segments, and turn the result into an action. ProductLens demonstrates that workflow as one inspectable path:

`Question → Metric → Analysis → Evidence → Insight → Decision → Action`

## The approach

ProductLens uses a centrally governed semantic catalog, trusted SQL compilers for high-value analytics, SQLGlot AST validation, a read-only PostgreSQL role, deterministic calculations, and controlled Plotly specifications. The Copilot is a structured investigation screen rather than an unbounded chat interface. Quick Answer gives the metric and comparison; Deep Dive checks relevant dimensions and ranks measured contributions.

## The flagship investigation

The deterministic generator injects a payment incident beginning 2026-08-18 for Mobile Safari sessions from Paid Social. The full seed validator measured the segment payment-success rate at 86.9955% in the comparison week and 58.6873% in the incident week. The Deep Dive then surfaced the generated `Mobile / Safari / Paid Social` context with an evidence ID and sample size; no narrative answer is stored in the generator.

## Reproducibility

The portfolio profile uses seed `20260824`, is anchored to dataset-as-of `2026-08-24`, and produced 20,000 users, 120,000 sessions, 608,186 events, 12,000 subscriptions, and 25,000 transactions in the final local validation. The PostgreSQL database measured 179 MB, leaving headroom under the documented target.

## What this demonstrates

- governed metric definitions with explicit UTC periods;
- exact percentage-point versus relative changes;
- additive contribution and rate mix/performance decomposition;
- evidence-bound findings, recommendations, and follow-up questions;
- anonymous-session history without raw IP storage;
- safe degradation when model keys are unavailable, using deterministic wording.

## Limitations

The data is synthetic and observational. The application does not establish causality, does not provide authentication or cross-device history, and is not positioned as an enterprise-scale production system. Live provider scoring, public deployment, and screenshots remain explicitly tracked follow-ons in the implementation matrix.
