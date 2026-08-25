import pytest

from app.semantic.registry import registry


def test_required_metrics_are_governed() -> None:
    required = {
        "dau", "wau", "mau", "stickiness", "signup_conversion", "activation_rate",
        "checkout_conversion", "payment_success_rate", "mrr", "arr", "arpu",
        "revenue", "trial_to_paid", "churn_rate", "d1_retention", "d7_retention",
        "d30_retention", "feature_adoption",
    }
    assert required.issubset(registry.metrics)


def test_invalid_dimension_is_rejected() -> None:
    with pytest.raises(ValueError, match="not valid"):
        registry.validate_dimension("mrr", "browser")


def test_catalog_has_no_pii_columns() -> None:
    assert all(not table.pii_columns for table in registry.tables.values())

