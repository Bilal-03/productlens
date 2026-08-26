import pytest

from app.analytics.sql_compiler import (
    compile_acquisition,
    compile_feature_adoption,
    compile_metric,
    compile_retention_curve,
)
from app.analytics.time_ranges import resolve_period
from app.models.contracts import Filter
from app.security.sql_validator import SQLValidator
from app.semantic.registry import registry


@pytest.mark.parametrize("metric", list(registry.metrics))
def test_every_metric_compiles_to_safe_sql(metric: str) -> None:
    proposal = compile_metric(metric, resolve_period("last_30_days"))
    result = SQLValidator().validate(proposal.query)
    assert result.valid, f"{metric}: {result.errors}\n{proposal.query}"


@pytest.mark.parametrize("metric,dimension", [
    ("checkout_conversion", "browser"),
    ("activation_rate", "channel"),
    ("mrr", "plan"),
    ("revenue", "company_size"),
    ("d30_retention", "cohort"),
])
def test_key_segment_queries_compile_safely(metric: str, dimension: str) -> None:
    proposal = compile_metric(metric, resolve_period("last_90_days"), dimension)
    result = SQLValidator().validate(proposal.query)
    assert result.valid, result.errors


def test_filters_are_escaped_and_allowlisted() -> None:
    proposal = compile_metric(
        "checkout_conversion",
        resolve_period("last_week"),
        filters=[Filter(dimension="channel", value="Paid Social")],
    )
    result = SQLValidator().validate(proposal.query)
    assert result.valid, result.errors
    assert "Paid Social" in proposal.query


def test_in_filters_require_values() -> None:
    with pytest.raises(ValueError, match="at least one"):
        compile_metric(
            "checkout_conversion",
            resolve_period("last_week"),
            filters=[Filter(dimension="channel", operator="in", value=[])],
        )


@pytest.mark.parametrize("cohort_type", ["signup", "activation"])
def test_retention_curve_compiles_all_windows(cohort_type: str) -> None:
    proposal = compile_retention_curve(
        resolve_period("last_90_days"),
        [1, 7, 30],
        cohort_type=cohort_type,
        dimension="channel",
    )
    result = SQLValidator().validate(proposal.query)
    assert result.valid, result.errors
    assert "d1" in proposal.query
    assert "d7" in proposal.query
    assert "d30" in proposal.query


def test_retention_curve_rejects_unsupported_windows() -> None:
    with pytest.raises(ValueError, match="D1, D7, and D30"):
        compile_retention_curve(resolve_period("last_90_days"), [14])


@pytest.mark.parametrize("metric", ["visitors", "signups", "activated_users", "channel_conversion"])
def test_acquisition_stages_compile_to_safe_sql(metric: str) -> None:
    proposal = compile_metric(metric, resolve_period("last_week"), "campaign")
    validation = SQLValidator().validate(proposal.query)
    assert validation.valid, validation.errors
    assert "landing_page_viewed" in proposal.query
    assert "signup_completed" in proposal.query


@pytest.mark.parametrize("dimension", ["feature", "channel", "device", "plan"])
def test_feature_adoption_dimensions_compile_to_safe_sql(dimension: str) -> None:
    proposal = compile_feature_adoption(resolve_period("last_30_days"), dimension)
    validation = SQLValidator().validate(proposal.query)
    assert validation.valid, validation.errors
    assert "uses_per_adopter" in proposal.query
    assert "feature_d30_numerator" in proposal.query


def test_acquisition_does_not_accept_transaction_only_filters() -> None:
    with pytest.raises(ValueError, match="Acquisition filters"):
        compile_acquisition(
            resolve_period("last_week"),
            "channel",
            filters=[Filter(dimension="failure_reason", value="card_declined")],
        )


def test_paid_users_kpi_uses_successful_transactions_or_period_end_subscriptions() -> None:
    proposal = compile_metric("paid_users", resolve_period("last_week"), "channel")
    validation = SQLValidator().validate(proposal.query)
    assert validation.valid, validation.errors
    assert "t.status='success'" in proposal.query
    assert "sub.cancelled_at" in proposal.query
    assert set(validation.tables) == {"sessions", "subscriptions", "transactions", "users"}


@pytest.mark.parametrize(
    ("metric", "start_day", "end_day"),
    [("weekly_retention", 7, 14), ("monthly_retention", 30, 60)],
)
def test_windowed_retention_uses_mature_return_windows(metric: str, start_day: int, end_day: int) -> None:
    proposal = compile_metric(metric, resolve_period("last_90_days"))
    validation = SQLValidator().validate(proposal.query)
    assert validation.valid, validation.errors
    assert f"interval '{start_day} days'" in proposal.query
    assert f"interval '{end_day} days'" in proposal.query
    assert "NULL" not in proposal.query.split("SELECT", 1)[-1] or "NULLIF" in proposal.query
