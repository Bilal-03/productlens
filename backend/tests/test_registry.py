import pytest

from app.semantic.registry import registry


def test_required_metrics_are_governed() -> None:
    required = {
        "dau", "wau", "mau", "stickiness", "signup_conversion", "activation_rate",
        "checkout_conversion", "payment_success_rate", "mrr", "arr", "arpu",
        "revenue", "trial_to_paid", "churn_rate", "d1_retention", "d7_retention",
        "d30_retention", "weekly_retention", "monthly_retention", "feature_adoption",
        "visitors", "signups", "activated_users", "paid_users", "channel_conversion",
    }
    assert required.issubset(registry.metrics)


def test_invalid_dimension_is_rejected() -> None:
    with pytest.raises(ValueError, match="not valid"):
        registry.validate_dimension("mrr", "browser")


def test_catalog_has_no_pii_columns() -> None:
    assert all(not table.pii_columns for table in registry.tables.values())


def test_catalog_exposes_column_metadata_and_dataset_row_counts() -> None:
    catalog = registry.public_catalog_with_counts({"users": 800, "events": 12_345})
    users = next(table for table in catalog["tables"] if table["name"] == "users")
    events = next(table for table in catalog["tables"] if table["name"] == "events")
    assert users["row_count"] == 800
    assert events["row_count"] == 12_345
    assert users["column_metadata"][0]["data_type"] == "bigint"
    assert users["column_metadata"][0]["pii"] is False
