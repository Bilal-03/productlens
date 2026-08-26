"""PostgreSQL-backed API smoke tests.

These tests are intentionally opt-in.  Unit and contract tests must remain runnable
without Docker, while CI and the local ``make integration`` target run this module
against a migrated, smoke-seeded PostgreSQL instance.
"""

from __future__ import annotations

import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_DB_INTEGRATION") != "1",
        reason="PostgreSQL integration tests require RUN_DB_INTEGRATION=1",
    ),
]

client = TestClient(app)
SESSION_ID = "ci-postgres-integration-session"


def test_seed_metadata_is_available() -> None:
    response = client.get("/api/v1/metadata/dataset")

    assert response.status_code == 200
    payload = response.json()
    assert payload["dataset_as_of"] == "2026-08-24"
    assert payload["profile"] == "smoke"
    assert payload["row_counts"]["users"] == 800
    assert payload["row_counts"]["sessions"] == 4_500
    assert payload["row_counts"]["events"] > 0


def test_retention_and_cohort_routes_execute_against_postgres() -> None:
    retention = client.post(
        "/api/v1/analytics/retention",
        json={
            "cohort_type": "signup",
            "period": "last_90_days",
            "dimension": "channel",
            "windows": [1, 7, 30],
        },
    )

    assert retention.status_code == 200
    payload = retention.json()
    assert payload["type"] == "retention_analysis"
    assert payload["dataset_as_of"] == "2026-08-24"
    assert payload["sql"]["validated"] is True
    assert len(payload["heatmap"]["y_labels"]) > 0
    assert len(payload["heatmap"]["matrix"]) == len(payload["heatmap"]["y_labels"])
    assert len(payload["time_series"]["segments"]) > 1
    assert any(value is None for value in (row[2] for row in payload["heatmap"]["matrix"]))

    cohort = client.post(
        "/api/v1/analytics/cohort",
        json={"cohort_type": "activation", "period": "last_90_days", "windows": [1, 7, 30]},
    )

    assert cohort.status_code == 200
    cohort_payload = cohort.json()
    assert cohort_payload["type"] == "retention_analysis"
    assert cohort_payload["cohort_type"] == "activation"
    assert cohort_payload["sql"]["validated"] is True


def test_kpi_and_governed_copilot_execute_with_real_roles() -> None:
    kpi = client.post(
        "/api/v1/analytics/kpi",
        json={"metric": "mau", "period": "last_30_days"},
    )

    assert kpi.status_code == 200
    kpi_payload = kpi.json()
    assert kpi_payload["metric"]["name"] == "mau"
    assert "SELECT" in kpi_payload["sql"]["current"].upper()
    assert kpi_payload["current"][0]["value"] > 0

    copilot = client.post(
        "/api/v1/copilot/analyze",
        json={
            "question": "What is MAU for the last 30 days?",
            "mode": "quick",
            "session_id": SESSION_ID,
        },
    )

    assert copilot.status_code == 200
    copilot_payload = copilot.json()
    assert copilot_payload["type"] == "analysis"
    assert copilot_payload["metadata"]["dataset_as_of"] == "2026-08-24"
    assert copilot_payload["sql"]["validated"] is True
    assert copilot_payload["sql"]["row_count"] > 0

    reopened = client.get(
        f"/api/v1/history/{copilot_payload['metadata']['query_id']}",
        headers={"X-ProductLens-Session": SESSION_ID},
    )
    assert reopened.status_code == 200
    assert reopened.json()["metadata"]["query_id"] == copilot_payload["metadata"]["query_id"]


def test_completion_analytics_routes_execute_with_real_roles() -> None:
    acquisition = client.post(
        "/api/v1/analytics/acquisition",
        json={"period": "last_30_days", "dimension": "channel"},
    )
    assert acquisition.status_code == 200
    acquisition_payload = acquisition.json()
    assert acquisition_payload["type"] == "acquisition_analysis"
    assert acquisition_payload["segments"]
    assert {"visitors", "signups", "activated_users", "paid_users", "signup_conversion"}.issubset(
        acquisition_payload["segments"][0]
    )

    feature = client.post(
        "/api/v1/analytics/feature-adoption",
        json={"metric": "feature_adoption", "period": "last_30_days", "dimension": "feature"},
    )
    assert feature.status_code == 200
    feature_payload = feature.json()
    assert feature_payload["type"] == "feature_adoption_analysis"
    assert feature_payload["rows"]
    assert {"eligible_users", "total_uses", "uses_per_adopter", "feature_d30_sample_size"}.issubset(
        feature_payload["rows"][0]
    )

    overview = client.post("/api/v1/analytics/overview", json={"period": "last_30_days"})
    assert overview.status_code == 200
    overview_payload = overview.json()
    assert overview_payload["type"] == "overview_analysis"
    assert len(overview_payload["kpis"]) == 6
    assert overview_payload["revenue_trend"]["points"]


def test_full_profile_proactive_pulse_surfaces_checkout_incident() -> None:
    metadata = client.get("/api/v1/metadata/dataset")
    assert metadata.status_code == 200
    if metadata.json()["profile"] != "full":
        pytest.skip("The seeded checkout-incident assertion requires the full profile")

    pulse = client.get("/api/v1/insights/pulse", params={"period": "last_30_days", "limit": 20})

    assert pulse.status_code == 200
    payload = pulse.json()
    assert payload["type"] == "product_pulse"
    assert payload["sql"]["validated"] is True
    checkout_signals = [
        item
        for item in payload["items"]
        if item["metric"] in {"checkout_conversion", "payment_success_rate", "payment_failures"}
    ]
    assert checkout_signals
    assert all(item["severity"] in {"warning", "critical"} for item in checkout_signals)
    assert any(
        driver["segment"] == "Mobile / Safari / Paid Social"
        for item in checkout_signals
        for driver in item["drivers"]
    )

    report = client.get("/api/v1/reports/weekly")
    assert report.status_code == 200
    report_payload = report.json()
    assert [section["key"] for section in report_payload["sections"]] == [
        "growth",
        "activation",
        "engagement",
        "retention",
        "revenue",
    ]


def test_analytics_reader_cannot_reach_source_or_operational_schemas() -> None:
    url = get_settings().analytics_database_url.replace("postgresql+psycopg", "postgresql")
    with psycopg.connect(url, autocommit=True) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM analytics.users")
        assert cursor.fetchone()[0] == 800
        for query in ("SELECT COUNT(*) FROM core.users", "SELECT COUNT(*) FROM operational.dataset_metadata"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cursor.execute(query)

    app_url = get_settings().app_database_url.replace("postgresql+psycopg", "postgresql")
    with psycopg.connect(app_url, autocommit=True) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM operational.dataset_metadata")
        assert cursor.fetchone()[0] == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute("SELECT COUNT(*) FROM analytics.users")
