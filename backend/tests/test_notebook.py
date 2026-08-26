from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.routes import notebook_service
from app.main import app
from app.models.contracts import AnalysisResponse, NotebookInsight
from app.notebook.service import NotebookService


def analysis(query_id: UUID) -> AnalysisResponse:
    return AnalysisResponse(
        question="Why did checkout conversion fall?",
        mode="deep",
        headline="Checkout conversion fell on mobile",
        summary="Mobile Safari contributed the largest observed decline.",
        interpretation={
            "intent": "diagnostic",
            "metric": "checkout_conversion",
            "metric_label": "Checkout Conversion",
            "metric_definition": "Paid users divided by checkout starters.",
            "current_period": {"start": date(2026, 8, 17), "end": date(2026, 8, 24), "label": "Last week"},
            "comparison_period": {"start": date(2026, 8, 10), "end": date(2026, 8, 17), "label": "Previous week"},
            "dimensions": ["device", "browser"],
            "assumptions": [],
        },
        comparison={
            "current": {"label": "Last week", "value": 0.1, "formatted": "10.0%", "numerator": 100, "denominator": 1000},
            "previous": {"label": "Previous week", "value": 0.12, "formatted": "12.0%", "numerator": 120, "denominator": 1000},
            "absolute_delta": -0.02,
            "relative_delta": -1 / 6,
            "percentage_point_delta": -0.02,
        },
        chart={"chart_type": "line", "title": "Checkout conversion", "data": [], "x_labels": [], "y_labels": [], "matrix": [], "description": "Daily rate."},
        findings=[{"kind": "observed", "text": "Conversion decreased week over week.", "evidence_ids": ["metric"]}],
        drivers=[{"dimension": "browser", "segment": "Safari", "current_value": 0.08, "previous_value": 0.14, "contribution": -0.03, "share_of_change": 0.5, "sample_size": 500, "evidence_ids": ["safari"]}],
        evidence=[{"id": "metric", "label": "Checkout conversion", "value": "10.0%", "detail": "Observed value."}, {"id": "safari", "label": "Safari", "value": "8.0%", "detail": "Segment value."}],
        recommendations=[{"priority": "high", "action": "Inspect Safari checkout errors.", "expected_impact": "Recover conversion if the issue is technical.", "evidence_ids": ["safari"], "how_to_validate": "Compare payment failures after the fix."}],
        follow_up_questions=["Why did Safari decline?"],
        investigation_trace=["Resolved governed metric"],
        sql={"query": "SELECT 1", "purpose": "Test", "tables": ["events"], "metrics": ["checkout_conversion"], "validated": True, "row_count": 1},
        caveats=[],
        metadata={
            "query_id": str(query_id),
            "generated_at": datetime(2026, 8, 26, tzinfo=UTC),
            "dataset_as_of": date(2026, 8, 24),
            "provider": "deterministic",
            "confidence": "high",
            "timings": {"total_ms": 12},
        },
    )


class FakeDatabase:
    def __init__(self, query_id: UUID) -> None:
        self.history = {query_id: analysis(query_id).model_dump(mode="json")}
        self.saved: list[dict[str, Any]] = []

    def history_item(self, session_hash: str, query_id: UUID) -> dict[str, Any] | None:
        return self.history.get(query_id) if session_hash == "session-a" else None

    def insert_notebook_insight(self, *, session_hash: str, source_query_id: UUID, title: str, response: dict[str, Any]) -> dict[str, Any]:
        existing = next((item for item in self.saved if item["session_hash"] == session_hash and item["source_query_id"] == source_query_id), None)
        if existing:
            existing.update(title=title, response=response)
            return {key: value for key, value in existing.items() if key != "session_hash"}
        item = {"insight_id": uuid4(), "session_hash": session_hash, "source_query_id": source_query_id, "title": title, "response": response, "created_at": datetime(2026, 8, 26, tzinfo=UTC)}
        self.saved.append(item)
        return {key: value for key, value in item.items() if key != "session_hash"}

    def notebook_insights(self, session_hash: str, limit: int = 50) -> list[dict[str, Any]]:
        return [{key: value for key, value in item.items() if key != "session_hash"} for item in self.saved if item["session_hash"] == session_hash][:limit]

    def delete_notebook_insight(self, session_hash: str, insight_id: UUID) -> bool:
        before = len(self.saved)
        self.saved[:] = [item for item in self.saved if not (item["session_hash"] == session_hash and item["insight_id"] == insight_id)]
        return len(self.saved) < before


def test_notebook_save_is_idempotent_and_session_scoped() -> None:
    query_id = uuid4()
    database = FakeDatabase(query_id)
    service = NotebookService(database)  # type: ignore[arg-type]

    saved = service.save("session-a", query_id, "Checkout incident")
    saved_again = service.save("session-a", query_id, "Checkout incident")

    assert saved.title == "Checkout incident"
    assert saved.source_query_id == query_id
    assert saved_again.insight_id == saved.insight_id
    assert len(service.list("session-a")) == 1
    assert service.list("session-b") == []
    assert service.delete("session-a", saved.insight_id) is True
    assert service.delete("session-a", saved.insight_id) is False

    with pytest.raises(LookupError):
        service.save("session-b", query_id)


def test_notebook_routes_validate_session_limit_and_delete() -> None:
    query_id = uuid4()
    insight = NotebookInsight.model_validate({
        "insight_id": uuid4(),
        "source_query_id": query_id,
        "title": "Checkout incident",
        **analysis(query_id).model_dump(mode="json", include={"question", "mode", "headline", "summary", "interpretation", "comparison", "chart", "findings", "drivers", "evidence", "recommendations"}),
        "created_at": datetime(2026, 8, 26, tzinfo=UTC),
    })

    class StubNotebook:
        def list(self, session_hash: str, limit: int) -> list[NotebookInsight]:
            assert session_hash
            return [insight][:limit]

        def save(self, session_hash: str, source_query_id: UUID, title: str | None) -> NotebookInsight:
            assert session_hash and source_query_id == query_id
            return insight

        def delete(self, session_hash: str, insight_id: UUID) -> bool:
            return insight_id == insight.insight_id

    app.dependency_overrides[notebook_service] = lambda: StubNotebook()  # type: ignore[assignment]
    client = TestClient(app)
    headers = {"X-ProductLens-Session": "notebook-api-contract-session"}
    try:
        assert client.get("/api/v1/notebook/insights", headers=headers).json()["type"] == "analysis_notebook"
        assert client.get("/api/v1/notebook/insights?limit=51", headers=headers).status_code == 422
        assert client.post("/api/v1/notebook/insights", headers=headers, json={"source_query_id": str(query_id)}).status_code == 201
        assert client.delete(f"/api/v1/notebook/insights/{insight.insight_id}", headers=headers).status_code == 204
        assert client.get("/api/v1/notebook/insights").status_code == 422
    finally:
        app.dependency_overrides.clear()
