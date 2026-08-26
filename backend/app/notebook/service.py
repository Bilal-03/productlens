from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.database.service import DatabaseService
from app.models.contracts import AnalysisResponse, NotebookInsight


class NotebookService:
    """Persist and project validated Copilot responses for one browser session."""

    def __init__(self, database: DatabaseService) -> None:
        self.database = database

    def save(self, session_hash: str, source_query_id: UUID, title: str | None = None) -> NotebookInsight:
        raw = self.database.history_item(session_hash, source_query_id)
        if not raw or raw.get("type") != "analysis":
            raise LookupError("Analysis not found for this session")
        try:
            analysis = AnalysisResponse.model_validate(raw)
        except ValidationError as exc:
            raise LookupError("Analysis not found for this session") from exc

        saved_title = self._title(title, analysis)
        row = self.database.insert_notebook_insight(
            session_hash=session_hash,
            source_query_id=source_query_id,
            title=saved_title,
            response=analysis.model_dump(mode="json"),
        )
        return self._project(row)

    def list(self, session_hash: str, limit: int = 50) -> list[NotebookInsight]:
        insights: list[NotebookInsight] = []
        for row in self.database.notebook_insights(session_hash, limit):
            try:
                insights.append(self._project(row))
            except (TypeError, ValueError, ValidationError):
                # A malformed historical snapshot should not take down the whole board.
                continue
        return insights

    def delete(self, session_hash: str, insight_id: UUID) -> bool:
        return self.database.delete_notebook_insight(session_hash, insight_id)

    @staticmethod
    def _title(title: str | None, analysis: AnalysisResponse) -> str:
        candidate = (title or "").strip() or analysis.question.strip() or analysis.headline.strip()
        return candidate[:160] or "Saved analysis"

    @staticmethod
    def _decode_response(value: Any) -> dict[str, Any]:
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict):
            raise ValueError("Saved insight response is not an object")
        return value

    @classmethod
    def _project(cls, row: dict[str, Any]) -> NotebookInsight:
        analysis = AnalysisResponse.model_validate(cls._decode_response(row.get("response")))
        created_at = row.get("created_at")
        if not isinstance(created_at, datetime):
            created_at = datetime.now(UTC)
        return NotebookInsight(
            insight_id=row["insight_id"],
            source_query_id=row["source_query_id"],
            title=str(row.get("title") or analysis.question)[:160],
            question=analysis.question,
            mode=analysis.mode,
            headline=analysis.headline,
            summary=analysis.summary,
            interpretation=analysis.interpretation,
            comparison=analysis.comparison,
            chart=analysis.chart,
            findings=analysis.findings,
            drivers=analysis.drivers,
            evidence=analysis.evidence,
            recommendations=analysis.recommendations,
            created_at=created_at,
        )
