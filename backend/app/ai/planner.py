from __future__ import annotations

import re
from dataclasses import dataclass

from app.analytics.time_ranges import default_comparison, resolve_period
from app.models.contracts import AnalyticsPlan, ClarificationOption, Intent
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
    def plan(self, question: str, selected_metric: str | None = None) -> AnalyticsPlan | AmbiguousQuestion | AdHocQuestion:
        normalized = re.sub(r"[!?.,]+$", "", " ".join(question.lower().split()))
        if UNSAFE_LANGUAGE.search(normalized):
            raise UnsafeQuestion("The request contains an unsupported database operation")
        if normalized in {"how are we doing", "what should we focus on", "give me an overview"}:
            return AmbiguousQuestion(
                reason="That question does not identify a governed metric or decision context.",
                options=[self._option("mau"), self._option("revenue"), self._option("activation_rate")],
            )
        if "conversion" in normalized and not selected_metric and not any(
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
        if metric == "feature_adoption" and not any(
            phrase in normalized for phrase in ("which feature", "rank feature", "by feature", "feature use")
        ):
            dimensions = [dimension for dimension in dimensions if dimension != "feature"]
        if intent == Intent.DIAGNOSTIC and not dimensions:
            dimensions = ["checkout_context", "device", "browser", "channel"] if metric in {"checkout_conversion", "payment_success_rate"} else ["plan", "channel", "company_size"]
        if intent in {Intent.RANKING, Intent.SEGMENTATION} and not dimensions:
            dimensions = ["channel"]
        if intent == Intent.COHORT and not dimensions:
            dimensions = ["cohort"]
        dimensions = [item for item in dimensions if item in registry.metric(metric).valid_dimensions]
        comparison = default_comparison(period_name) if intent in {Intent.COMPARISON, Intent.DIAGNOSTIC, Intent.TREND} else None
        return AnalyticsPlan(
            intent=intent,
            metric=metric,
            time_range=resolve_period(period_name),
            comparison=comparison,
            dimensions=dimensions,
            requires_segmentation=bool(dimensions),
            requires_comparison=comparison is not None,
            assumptions=["Relative dates use the synthetic dataset reference date", "All dates are UTC"],
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
        }
        return [dimension for dimension, terms in aliases.items() if any(term in question for term in terms)]
