from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from app.analytics.time_ranges import DATASET_AS_OF, default_comparison, resolve_period
from app.models.contracts import AnalyticsPlan, ClarificationOption, Filter, Intent
from app.semantic.registry import registry


@dataclass(frozen=True)
class AmbiguousQuestion:
    reason: str
    options: list[ClarificationOption]


@dataclass(frozen=True)
class AdHocQuestion:
    """A well-formed question that is outside the governed metric templates."""

    reason: str = "This question requires a read-only query over the approved analytics catalog."


UNSAFE_LANGUAGE = re.compile(
    r"\b(drop|delete|update|insert|alter|truncate|create|grant|revoke|copy|execute|call|pg_catalog|information_schema)\b",
    re.IGNORECASE,
)


class UnsafeQuestion(ValueError):
    pass


class QuestionPlanner:
    def plan(
        self,
        question: str,
        selected_metric: str | None = None,
        *,
        as_of: date = DATASET_AS_OF,
    ) -> AnalyticsPlan | AmbiguousQuestion | AdHocQuestion:
        normalized = re.sub(r"[!?.,]+$", "", " ".join(question.lower().split()))
        if UNSAFE_LANGUAGE.search(normalized):
            raise UnsafeQuestion("The request contains an unsupported database operation")
        if normalized in {"how are we doing", "what should we focus on", "give me an overview"}:
            return AmbiguousQuestion(
                reason="That question does not identify a governed metric or decision context.",
                options=[self._option("mau"), self._option("revenue"), self._option("activation_rate")],
            )
        if "conversion" in normalized and "channel conversion" not in normalized and not selected_metric and not any(
            word in normalized for word in ["checkout", "signup", "activation", "trial", "paid"]
        ):
            return AmbiguousQuestion(
                reason="Conversion has several governed definitions. Choose the journey you want to analyze.",
                options=[
                    self._option("signup_conversion"),
                    self._option("activation_rate"),
                    self._option("trial_to_paid"),
                    self._option("checkout_conversion"),
                ],
            )
        metric = selected_metric or self._metric_match(normalized)
        if metric is None:
            return AdHocQuestion()
        registry.metric(metric)
        period_name = self._period(normalized)
        intent = self._intent(normalized, metric)
        dimensions = self._dimensions(normalized)
        filters = self._filters(normalized, metric)
        # In "channel conversion" the word channel names the governed metric,
        # not necessarily a requested breakdown. Keep it only when the user
        # explicitly asks for channel segments (or says acquisition channel).
        if "channel conversion" in normalized and not any(
            phrase in normalized for phrase in ("by channel", "per channel", "acquisition channel")
        ):
            dimensions = [dimension for dimension in dimensions if dimension != "channel"]
        if metric == "feature_adoption" and not any(
            phrase in normalized for phrase in ("which feature", "rank feature", "by feature", "feature use")
        ):
            dimensions = [dimension for dimension in dimensions if dimension != "feature"]
        if intent == Intent.DIAGNOSTIC and not dimensions:
            dimensions = ["checkout_context", "device", "browser", "channel"] if metric in {"checkout_conversion", "payment_success_rate"} else ["plan", "channel", "company_size", "customer_type", "revenue_motion", "failure_reason"]
        if intent in {Intent.RANKING, Intent.SEGMENTATION} and not dimensions:
            dimensions = ["channel"]
        if intent == Intent.COHORT and not dimensions:
            dimensions = ["cohort"]
        dimensions = [item for item in dimensions if item in registry.metric(metric).valid_dimensions]
        comparison = default_comparison(period_name, as_of) if intent in {Intent.COMPARISON, Intent.DIAGNOSTIC, Intent.TREND} else None
        return AnalyticsPlan(
            intent=intent,
            metric=metric,
            time_range=resolve_period(period_name, as_of),
            comparison=comparison,
            dimensions=dimensions,
            requires_segmentation=bool(dimensions),
            requires_comparison=comparison is not None,
            filters=filters,
            assumptions=[
                f"Relative dates use the source data horizon ending {as_of.isoformat()}",
                "All dates are UTC",
                *(["Explicit segment filters are applied before metric calculation"] if filters else []),
            ],
        )

    @staticmethod
    def _option(metric: str) -> ClarificationOption:
        definition = registry.metric(metric)
        return ClarificationOption(metric=metric, label=definition.label, definition=definition.description)

    @staticmethod
    def _metric_match(question: str) -> str | None:
        mappings = [
            (("stickiness", "sticky"), "stickiness"),
            (("feature", "behaviour", "behavior"), "feature_adoption"),
            (("weekly retention", "weekly return"), "weekly_retention"),
            (("monthly retention", "monthly return"), "monthly_retention"),
            (("channel conversion", "acquisition channel converts"), "channel_conversion"),
            (("visitors", "visitor count"), "visitors"),
            (("activated users",), "activated_users"),
            (("paid users",), "paid_users"),
            (("signups", "sign ups"), "signups"),
            (("onboarding",), "activation_rate"),
            (("cohort",), "d30_retention"),
            (("checkout", "payment conversion"), "checkout_conversion"),
            (("payment success", "payment fail"), "payment_success_rate"),
            (("activation", "activated"), "activation_rate"),
            (("acquisition", "signup", "converts", "signup conversion", "visitor"), "signup_conversion"),
            (("d30", "30 retention"), "d30_retention"),
            (("d7", "7 retention"), "d7_retention"),
            (("d1", "retention"), "d1_retention"),
            (("mrr",), "mrr"),
            (("arr",), "arr"),
            (("arpu",), "arpu"),
            (("churn",), "churn_rate"),
            (("trial",), "trial_to_paid"),
            (("revenue",), "revenue"),
            (("mau", "monthly active"), "mau"),
            (("wau", "weekly active"), "wau"),
            (("dau", "daily active"), "dau"),
        ]
        for terms, metric in mappings:
            if any(term in question for term in terms):
                return metric
        return None

    @staticmethod
    def _metric(question: str) -> str:
        """Return a backward-compatible default for callers that need a metric."""

        return QuestionPlanner._metric_match(question) or "mau"

    @staticmethod
    def _period(question: str) -> str:
        if "last week" in question or "week over week" in question or "wow" in question:
            return "last_week"
        if "last month" in question:
            return "last_month"
        if "this month" in question:
            return "this_month"
        if "90 day" in question or "cohort" in question:
            return "last_90_days"
        if "7 day" in question:
            return "last_7_days"
        return "last_30_days"

    @staticmethod
    def _intent(question: str, metric: str) -> Intent:
        if question.startswith("why") or any(term in question for term in ["drove", "driver", "cause", "decline"]):
            return Intent.DIAGNOSTIC
        if "funnel" in question or "drop" in question and "onboarding" in question:
            return Intent.FUNNEL
        if "cohort" in question:
            return Intent.COHORT
        if metric == "feature_adoption" and any(term in question for term in ["associated", "better retention"]):
            return Intent.FEATURE_ADOPTION
        if any(term in question for term in ["which", "best", "most", "highest", "lowest", "rank"]):
            return Intent.RANKING
        if any(term in question for term in ["compare", "differ", " by "]):
            return Intent.SEGMENTATION
        if any(term in question for term in ["trend", "over time", "changed", "week over week"]):
            return Intent.COMPARISON
        if "change" in question or "changed" in question:
            return Intent.COMPARISON
        if metric == "feature_adoption":
            return Intent.FEATURE_ADOPTION
        if "retention" in question:
            return Intent.RETENTION
        if QuestionPlanner._dimensions(question):
            return Intent.SEGMENTATION
        if metric in {"mrr", "arr", "arpu", "revenue", "churn_rate", "trial_to_paid"}:
            return Intent.REVENUE
        return Intent.KPI

    @staticmethod
    def _dimensions(question: str) -> list[str]:
        aliases = {
            "channel": ["channel", "acquisition"],
            "campaign": ["campaign"],
            "country": ["country", "countries"],
            "device": ["device", "mobile", "desktop"],
            "browser": ["browser", "safari", "chrome"],
            "plan": ["plan"],
            "company_size": ["company size", "smb", "enterprise"],
            "feature": ["feature"],
            "payment_method": ["payment method"],
            "customer_type": ["new customer", "returning customer", "new customers", "returning customers"],
            "revenue_motion": ["renewal", "renewals", "charge", "charges", "refund", "refunds"],
            "failure_reason": ["failure reason", "failed payment", "failed payments", "declined"],
        }
        return [dimension for dimension, terms in aliases.items() if any(term in question for term in terms)]

    @staticmethod
    def _filters(question: str, metric: str) -> list[Filter]:
        """Resolve only explicit, low-risk natural-language segment filters.

        Dimension mentions such as ``by browser`` are breakdowns, not filters.
        A filter is accepted only when a known catalog value follows a scoped
        marker (``for``, ``in``, ``from``, ``among``, or ``within``) or an
        explicit ``dimension = value``/``dimension is value`` expression.
        Unknown values are left for the normal ambiguity/ad-hoc path.
        """

        valid_dimensions = set(registry.metric(metric).valid_dimensions)
        values: dict[str, tuple[str, ...]] = {
            "channel": ("paid social", "organic search", "paid search", "direct", "referral"),
            "country": ("united states", "united kingdom", "india", "germany"),
            "device": ("mobile", "desktop", "tablet"),
            "browser": ("safari", "chrome", "firefox", "edge"),
            "plan": ("business", "starter", "pro", "free"),
            "company_size": ("mid-market", "enterprise", "smb", "solo"),
            "payment_method": ("card", "paypal", "bank transfer"),
            "customer_type": ("new customer", "returning customer"),
            "revenue_motion": ("renewal", "charge", "refund"),
            "failure_reason": (
                "card declined",
                "renewal declined",
                "insufficient funds",
                "card_declined",
                "renewal_declined",
                "insufficient_funds",
            ),
        }
        aliases = {
            "company size": "company_size",
            "payment method": "payment_method",
            "customer type": "customer_type",
            "revenue motion": "revenue_motion",
            "failure reason": "failure_reason",
            "channel": "channel",
            "country": "country",
            "device": "device",
            "browser": "browser",
            "plan": "plan",
        }
        found: dict[str, str] = {}
        scoped_markers = r"(?:for|in|from|among|within)"
        for dimension, candidates in values.items():
            if dimension not in valid_dimensions:
                continue
            for candidate in sorted(candidates, key=len, reverse=True):
                escaped = re.escape(candidate)
                if re.search(rf"\b{scoped_markers}\s+(?:the\s+)?{escaped}\b", question):
                    found[dimension] = QuestionPlanner._canonical_filter_value(dimension, candidate)
                    break
        for label, dimension in aliases.items():
            if dimension not in valid_dimensions:
                continue
            candidates = values.get(dimension, ())
            for candidate in sorted(candidates, key=len, reverse=True):
                if re.search(rf"\b{re.escape(label)}\s*(?:=|is|of)\s*{re.escape(candidate)}\b", question):
                    found[dimension] = QuestionPlanner._canonical_filter_value(dimension, candidate)
                    break
        return [Filter(dimension=dimension, value=value) for dimension, value in sorted(found.items())]

    @staticmethod
    def _canonical_filter_value(dimension: str, candidate: str) -> str:
        normalized = candidate.lower().replace(" ", "_")
        definition = registry.dimensions.get(dimension)
        if definition:
            for sample in definition.sample_values:
                if sample.lower().replace(" ", "_") == normalized:
                    return sample
        return candidate
