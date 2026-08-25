from fastapi.testclient import TestClient

from app.api.routes import analytics_service
from app.main import app
from app.models.contracts import RetentionAnalyticsResponse

client = TestClient(app)


def test_root_and_catalog_contracts() -> None:
    assert client.get("/").status_code == 200
    response = client.get("/api/v1/catalog")
    assert response.status_code == 200
    assert {"metrics", "dimensions", "tables"} == set(response.json())


def test_request_body_limit() -> None:
    response = client.post(
        "/api/v1/copilot/analyze",
        content="x" * 33_000,
        headers={"content-type": "application/json", "content-length": "33000"},
    )
    assert response.status_code == 413


def test_retention_route_returns_heatmap_contract() -> None:
    class StubAnalytics:
        def retention(self, request: object) -> dict[str, object]:
            return RetentionAnalyticsResponse(
                cohort_type="signup",
                period={"start": "2026-05-26", "end": "2026-08-24", "label": "Last 90 Days"},
                dataset_as_of="2026-08-24",
                dimension=None,
                windows=[{"day": 1, "label": "D1 Retention", "metric": "d1_retention"}],
                heatmap={"x_labels": ["D1"], "y_labels": ["2026-07-20"], "matrix": [[0.5]], "cohort_sizes": [100]},
                time_series={"points": [{"period": "2026-07-20", "segment": "All", "window": "D1", "value": 0.5}], "segments": ["All"]},
                sql={"heatmap": "SELECT 1", "trend": "SELECT 1", "tables": ["users"], "metrics": ["d1_retention"], "validated": True},
                execution_ms=1.0,
            ).model_dump(mode="json")

    app.dependency_overrides[analytics_service] = lambda: StubAnalytics()  # type: ignore[assignment]
    try:
        response = client.post(
            "/api/v1/analytics/retention",
            json={"cohort_type": "signup", "period": "last_90_days", "windows": [1]},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["type"] == "retention_analysis"
    assert response.json()["heatmap"]["matrix"] == [[0.5]]
