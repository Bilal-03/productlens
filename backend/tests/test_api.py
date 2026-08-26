from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.routes import analytics_service, database_service, proactive_service
from app.main import app
from app.models.contracts import (
    AcquisitionAnalyticsResponse,
    AcquisitionSegment,
    AnomaliesResponse,
    AnomalyMethodology,
    AnomalyRecord,
    DateRange,
    Evidence,
    FeatureAdoptionAnalyticsResponse,
    FeatureAdoptionRow,
    OverviewAnalyticsResponse,
    ProactiveMetadata,
    ProactiveSQLTransparency,
    ProductPulseResponse,
    ReportSection,
    RetentionAnalyticsResponse,
    WeeklyReportResponse,
)
from app.security.session import hash_session

client = TestClient(app)


def test_root_and_catalog_contracts() -> None:
    assert client.get("/").status_code == 200
    response = client.get("/api/v1/catalog")
    assert response.status_code == 200
    assert {"metrics", "dimensions", "tables"} == set(response.json())
    users = next(table for table in response.json()["tables"] if table["name"] == "users")
    assert "row_count" in users
    assert users["column_metadata"][0]["data_type"]
    assert users["pii_columns"] == []


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


def _retention_payload() -> RetentionAnalyticsResponse:
    return RetentionAnalyticsResponse(
        cohort_type="signup",
        period={"start": "2026-05-26", "end": "2026-08-24", "label": "Last 90 Days"},
        dataset_as_of=date(2026, 8, 24),
        dimension=None,
        windows=[{"day": 1, "label": "D1 Retention", "metric": "d1_retention"}],
        heatmap={"x_labels": ["D1"], "y_labels": ["2026-07-20"], "matrix": [[0.5]], "cohort_sizes": [100]},
        time_series={"points": [{"period": "2026-07-20", "segment": "All", "window": "D1", "value": 0.5}], "segments": ["All"]},
        sql={"heatmap": "SELECT 1", "trend": "SELECT 1", "tables": ["users"], "metrics": ["d1_retention"], "validated": True},
        execution_ms=1.0,
    )


def test_new_analytics_routes_return_typed_contracts() -> None:
    acquisition = AcquisitionAnalyticsResponse(
        period={"start": "2026-08-17", "end": "2026-08-24", "label": "Last Week"},
        comparison_period=None,
        dataset_as_of=date(2026, 8, 24),
        dimension="channel",
        segments=[AcquisitionSegment(segment="Organic Search", visitors=10, signups=5, activated_users=4, paid_users=2, signup_conversion=0.5, activation_conversion=0.8, paid_conversion=0.4)],
        sql={"query": "SELECT 1", "purpose": "test", "tables": ["events"], "metrics": ["visitors"], "validated": True, "row_count": 1},
        execution_ms=1.0,
    )
    feature = FeatureAdoptionAnalyticsResponse(
        period={"start": "2026-08-17", "end": "2026-08-24", "label": "Last Week"},
        comparison_period=None,
        dataset_as_of=date(2026, 8, 24),
        dimension="feature",
        rows=[FeatureAdoptionRow(feature="Exports", eligible_users=10, adopting_users=4, adoption_rate=0.4, total_uses=8, uses_per_adopter=2, feature_user_d30=0.5, non_feature_user_d30=0.3, association_delta=0.2)],
        sql={"query": "SELECT 1", "purpose": "test", "tables": ["events"], "metrics": ["feature_adoption"], "validated": True, "row_count": 1},
        execution_ms=1.0,
    )
    overview = OverviewAnalyticsResponse(
        period={"start": "2026-08-17", "end": "2026-08-24", "label": "Last Week"},
        comparison_period=None,
        dataset_as_of=date(2026, 8, 24),
        kpis={"mau": {"current": [{"value": 10}]}},
        revenue_trend={"points": [{"label": "2026-08-17", "value": 10}]},
        user_growth_trend={"points": [{"label": "2026-08-17", "value": 4}]},
        acquisition=acquisition,
        activation_funnel={"segments": {"All": [{"stage": "signup_completed", "users": 10}]}},
        retention_snapshot=_retention_payload(),
    )

    class StubAnalytics:
        def acquisition(self, request: object) -> dict[str, object]:
            return acquisition.model_dump(mode="json")

        def feature_adoption(self, request: object) -> dict[str, object]:
            return feature.model_dump(mode="json")

        def overview(self, request: object) -> dict[str, object]:
            return overview.model_dump(mode="json")

    app.dependency_overrides[analytics_service] = lambda: StubAnalytics()  # type: ignore[assignment]
    try:
        assert client.post("/api/v1/analytics/acquisition", json={}).status_code == 200
        assert client.post("/api/v1/analytics/feature-adoption", json={"metric": "feature_adoption"}).status_code == 200
        overview_response = client.post("/api/v1/analytics/overview", json={})
    finally:
        app.dependency_overrides.clear()
    assert overview_response.status_code == 200
    assert overview_response.json()["type"] == "overview_analysis"
    assert overview_response.json()["acquisition"]["segments"][0]["visitors"] == 10


def test_history_reopen_is_session_scoped_and_does_not_consume_quota() -> None:
    query_id = uuid4()
    session = "api-contract-history-session"
    captured: dict[str, object] = {}

    class StubDatabase:
        def history_item(self, session_hash: str, requested_id: object) -> dict[str, object]:
            captured["session_hash"] = session_hash
            captured["query_id"] = requested_id
            return {"type": "analysis", "query_id": str(query_id)}

    app.dependency_overrides[database_service] = lambda: StubDatabase()  # type: ignore[assignment]
    try:
        response = client.get(f"/api/v1/history/{query_id}", headers={"X-ProductLens-Session": session})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"type": "analysis", "query_id": str(query_id)}
    assert captured["query_id"] == query_id
    assert captured["session_hash"] == hash_session(session, "development-only-secret-change-me")


def test_proactive_routes_return_typed_json_and_markdown_contracts() -> None:
    period = DateRange(start=date(2026, 8, 17), end=date(2026, 8, 24), label="Last completed week")
    methodology = AnomalyMethodology(
        policy_version="rolling-zscore-v1",
        analysis_period=DateRange(start=date(2026, 5, 26), end=date(2026, 8, 24), label="Last 90 Days"),
        baseline_days=28,
        minimum_baseline_points=14,
        minimum_sample_size=100,
        z_score_threshold=2,
        rate_change_threshold=0.1,
        count_change_threshold=0.15,
    )
    evidence = [Evidence(id="anomaly-metric", label="Checkout Conversion anomaly", value="10.0% vs 12.0%", detail="Test evidence")]
    anomaly = AnomalyRecord(
        id="anomaly-checkout_conversion-2026-08-18",
        metric="checkout_conversion",
        metric_label="Checkout Conversion",
        metric_format="percentage",
        period=period,
        observed={"label": "Aug 18, 2026", "value": 0.1, "formatted": "10.0%"},
        baseline={"label": "28-day rolling baseline", "value": 0.12, "formatted": "12.0%"},
        absolute_delta=-0.02,
        relative_delta=-1 / 6,
        z_score=-3.0,
        direction="decrease",
        severity="critical",
        sample_size=500,
        evidence_ids=["anomaly-metric"],
        summary="Checkout Conversion decreased to 10.0%.",
        copilot_question="Why did checkout conversion decrease?",
    )
    sql = ProactiveSQLTransparency(tables=["events"], metrics=["checkout_conversion"], query_count=1, validated=True)
    metadata = ProactiveMetadata(generated_at="2026-08-26T00:00:00Z", execution_ms=1)
    anomaly_response = AnomaliesResponse(
        period=period,
        dataset_as_of=date(2026, 8, 24),
        anomalies=[anomaly],
        evidence=evidence,
        methodology=methodology,
        sql=sql,
        metadata=metadata,
    )
    pulse_response = ProductPulseResponse(
        period=period,
        dataset_as_of=date(2026, 8, 24),
        items=[anomaly],
        evidence=evidence,
        methodology=methodology,
        sql=sql,
        metadata=metadata,
    )
    report_response = WeeklyReportResponse(
        period=period,
        comparison_period=DateRange(start=date(2026, 8, 10), end=date(2026, 8, 17), label="Previous completed week"),
        dataset_as_of=date(2026, 8, 24),
        headline="Checkout Conversion is the strongest weekly signal",
        summary="Checkout Conversion decreased to 10.0%.",
        sections=[ReportSection(key="growth", title="Growth", summary="Growth is stable.", metrics=[])],
        anomalies=[anomaly],
        drivers=[],
        evidence=evidence,
        recommendations=[],
        follow_up_questions=["What changed?", "Where did it change?"],
        caveats=[],
        methodology=methodology,
        sql=sql,
        metadata=metadata,
    )

    class StubProactive:
        def anomalies(self, period_name: str, limit: int) -> AnomaliesResponse:
            assert period_name == "last_30_days"
            assert limit == 50
            return anomaly_response

        def pulse(self, period_name: str, limit: int) -> ProductPulseResponse:
            assert period_name == "last_30_days"
            assert limit == 20
            return pulse_response

        def weekly_report(self, period_name: str) -> WeeklyReportResponse:
            assert period_name == "last_week"
            return report_response

    app.dependency_overrides[proactive_service] = lambda: StubProactive()  # type: ignore[assignment]
    try:
        assert client.get("/api/v1/insights/anomalies").status_code == 200
        assert client.get("/api/v1/insights/pulse").json()["type"] == "product_pulse"
        report = client.get("/api/v1/reports/weekly")
        assert report.status_code == 200
        markdown = client.get("/api/v1/reports/weekly/markdown")
    finally:
        app.dependency_overrides.clear()
    assert markdown.status_code == 200
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert "attachment" in markdown.headers["content-disposition"]
    assert "# ProductLens Weekly Product Report" in markdown.text


def test_proactive_routes_reject_invalid_periods_and_limits() -> None:
    assert client.get("/api/v1/insights/anomalies", params={"limit": 0}).status_code == 422
    assert client.get("/api/v1/insights/pulse", params={"limit": 51}).status_code == 422
    assert client.get("/api/v1/insights/anomalies", params={"period": "tomorrow"}).status_code == 422
    assert client.get("/api/v1/reports/weekly", params={"period": "last_30_days"}).status_code == 422
