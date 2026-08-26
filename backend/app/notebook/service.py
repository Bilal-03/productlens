from __future__ import annotations

import json
from builtins import list as list_type
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.database.service import DatabaseService
from app.models.contracts import (
    AnalysisResponse,
    NotebookInsight,
    NotebookSummary,
    NotebookSummaryDriver,
    NotebookSummaryFinding,
    NotebookSummaryMethodology,
    NotebookSummaryRecommendation,
    NotebookSummaryTheme,
)


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
        insights: list_type[NotebookInsight] = []
        for row in self.database.notebook_insights(session_hash, limit):
            try:
                insights.append(self._project(row))
            except (TypeError, ValueError, ValidationError):
                # A malformed historical snapshot should not take down the whole board.
                continue
        return insights

    def delete(self, session_hash: str, insight_id: UUID) -> bool:
        return self.database.delete_notebook_insight(session_hash, insight_id)

    def summary(self, session_hash: str, limit: int = 50) -> NotebookSummary | None:
        """Aggregate saved, validated snapshots without rerunning analytics."""

        insights = self.list(session_hash, limit)
        if not insights:
            return None

        source_insight_ids = [item.insight_id for item in insights]
        themes = self._themes(insights)
        findings = self._findings(insights)
        drivers = self._drivers(insights)
        recommendations = self._recommendations(insights)
        metric_labels = [theme.metric_label for theme in themes]
        if len(insights) == 1:
            headline = f"Executive summary: {insights[0].headline}"
            summary = insights[0].summary
        else:
            headline = f"Executive summary across {len(insights)} saved investigations"
            labels = ", ".join(metric_labels[:3])
            if len(metric_labels) > 3:
                labels += f", and {len(metric_labels) - 3} more"
            summary = f"This board combines validated snapshots across {labels}. {themes[0].summary}"

        return NotebookSummary(
            generated_at=datetime.now(UTC),
            headline=headline,
            summary=summary,
            source_insight_ids=source_insight_ids,
            themes=themes,
            findings=findings,
            drivers=drivers,
            recommendations=recommendations,
            methodology=NotebookSummaryMethodology(
                source_insight_count=len(insights),
            ),
        )

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

    @staticmethod
    def _unique(values: list_type[str]) -> list_type[str]:
        return list(dict.fromkeys(value for value in values if value))

    @classmethod
    def _valid_evidence(cls, insight: NotebookInsight, evidence_ids: list_type[str]) -> list_type[str]:
        valid_ids = {item.id for item in insight.evidence}
        return cls._unique([evidence_id for evidence_id in evidence_ids if evidence_id in valid_ids])

    @classmethod
    def _themes(cls, insights: list_type[NotebookInsight]) -> list_type[NotebookSummaryTheme]:
        grouped: dict[str, list_type[NotebookInsight]] = {}
        for insight in insights:
            grouped.setdefault(insight.interpretation.metric, []).append(insight)
        themes: list_type[NotebookSummaryTheme] = []
        for metric, items in grouped.items():
            first = items[0]
            themes.append(
                NotebookSummaryTheme(
                    metric=metric,
                    metric_label=first.interpretation.metric_label,
                    insight_count=len(items),
                    headline=first.headline,
                    summary=first.summary,
                    evidence_ids=cls._unique([evidence.id for item in items for evidence in item.evidence]),
                    source_insight_ids=[item.insight_id for item in items],
                )
            )
        return sorted(themes, key=lambda item: (-item.insight_count, item.metric))

    @classmethod
    def _findings(cls, insights: list_type[NotebookInsight]) -> list_type[NotebookSummaryFinding]:
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for insight in insights:
            for finding in insight.findings:
                evidence_ids = cls._valid_evidence(insight, finding.evidence_ids)
                if not evidence_ids:
                    continue
                key = (str(finding.kind), finding.text.strip())
                entry = grouped.setdefault(
                    key,
                    {"finding": finding, "evidence_ids": [], "source_insight_ids": []},
                )
                entry["evidence_ids"] = cls._unique([*entry["evidence_ids"], *evidence_ids])
                if insight.insight_id not in entry["source_insight_ids"]:
                    entry["source_insight_ids"].append(insight.insight_id)
        return [
            NotebookSummaryFinding(
                kind=entry["finding"].kind,
                text=entry["finding"].text,
                evidence_ids=entry["evidence_ids"],
                source_insight_ids=entry["source_insight_ids"],
            )
            for entry in list(grouped.values())[:6]
        ]

    @classmethod
    def _drivers(cls, insights: list_type[NotebookInsight]) -> list_type[NotebookSummaryDriver]:
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for insight in insights:
            for driver in insight.drivers:
                evidence_ids = cls._valid_evidence(insight, driver.evidence_ids)
                if not evidence_ids:
                    continue
                key = (driver.dimension, driver.segment)
                entry = grouped.get(key)
                if entry is None or abs(driver.contribution) > abs(entry["driver"].contribution):
                    entry = grouped.setdefault(
                        key,
                        {"driver": driver, "evidence_ids": [], "source_insight_ids": []},
                    )
                    entry["driver"] = driver
                entry["evidence_ids"] = cls._unique([*entry["evidence_ids"], *evidence_ids])
                if insight.insight_id not in entry["source_insight_ids"]:
                    entry["source_insight_ids"].append(insight.insight_id)
        ordered = sorted(
            grouped.values(),
            key=lambda entry: (-abs(entry["driver"].contribution), entry["driver"].dimension, entry["driver"].segment),
        )
        drivers: list_type[NotebookSummaryDriver] = []
        for entry in ordered[:8]:
            driver_data = entry["driver"].model_dump()
            driver_data["evidence_ids"] = entry["evidence_ids"]
            driver_data["source_insight_ids"] = entry["source_insight_ids"]
            drivers.append(NotebookSummaryDriver.model_validate(driver_data))
        return drivers

    @classmethod
    def _recommendations(cls, insights: list_type[NotebookInsight]) -> list_type[NotebookSummaryRecommendation]:
        priority_rank = {"high": 0, "medium": 1, "low": 2}
        grouped: dict[str, dict[str, Any]] = {}
        for insight in insights:
            for recommendation in insight.recommendations:
                evidence_ids = cls._valid_evidence(insight, recommendation.evidence_ids)
                if not evidence_ids:
                    continue
                key = recommendation.action.strip().lower()
                entry = grouped.get(key)
                if entry is None or priority_rank[recommendation.priority] < priority_rank[entry["recommendation"].priority]:
                    entry = grouped.setdefault(
                        key,
                        {"recommendation": recommendation, "evidence_ids": [], "source_insight_ids": []},
                    )
                    entry["recommendation"] = recommendation
                entry["evidence_ids"] = cls._unique([*entry["evidence_ids"], *evidence_ids])
                if insight.insight_id not in entry["source_insight_ids"]:
                    entry["source_insight_ids"].append(insight.insight_id)
        ordered = sorted(
            grouped.values(),
            key=lambda entry: (priority_rank[entry["recommendation"].priority], entry["recommendation"].action.lower()),
        )
        recommendations: list_type[NotebookSummaryRecommendation] = []
        for entry in ordered[:6]:
            recommendation_data = entry["recommendation"].model_dump()
            recommendation_data["evidence_ids"] = entry["evidence_ids"]
            recommendation_data["source_insight_ids"] = entry["source_insight_ids"]
            recommendations.append(NotebookSummaryRecommendation.model_validate(recommendation_data))
        return recommendations

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
