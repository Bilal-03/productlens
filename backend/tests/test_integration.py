"""PostgreSQL-backed API smoke tests.

These tests are intentionally opt-in.  Unit and contract tests must remain runnable
without Docker, while CI and the local ``make integration`` target run this module
against a migrated, smoke-seeded PostgreSQL instance.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

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
