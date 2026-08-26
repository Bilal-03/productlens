from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.ai.insights import InsightService
from app.ai.pipeline import CopilotPipeline
from app.ai.planner import QuestionPlanner
from app.ai.providers import ProviderRouter
from app.ai.sql_generation import SQLGenerator
from app.analytics.proactive import ProactiveAnalyticsService
from app.analytics.service import AnalyticsService
from app.config import Settings, get_settings
from app.database.service import DatabaseService, DatabaseUnavailable
from app.models.contracts import (
    AcquisitionAnalyticsResponse,
    AcquisitionRequest,
    AnalyticsRequest,
    AnomaliesResponse,
    CopilotRequest,
    CopilotResponse,
    FeatureAdoptionAnalyticsResponse,
    FunnelRequest,
    OverviewAnalyticsResponse,
    OverviewRequest,
    ProductPulseResponse,
    RetentionAnalyticsResponse,
    RetentionRequest,
    WeeklyReportResponse,
)
from app.security.session import hash_session
from app.security.sql_validator import SQLSafetyPolicy, SQLValidator
from app.semantic.registry import registry

router = APIRouter()


@lru_cache
def database_service() -> DatabaseService:
    return DatabaseService(get_settings())


@lru_cache
def sql_validator() -> SQLValidator:
    settings = get_settings()
    return SQLValidator(SQLSafetyPolicy(max_rows=settings.max_query_rows))


@lru_cache
def analytics_service() -> AnalyticsService:
    return AnalyticsService(database_service(), sql_validator())


@lru_cache
def copilot_pipeline() -> CopilotPipeline:
    settings = get_settings()
    provider_router = ProviderRouter(settings)
    return CopilotPipeline(
        settings=settings,
        database=database_service(),
        analytics=analytics_service(),
        planner=QuestionPlanner(),
        validator=sql_validator(),
        insights=InsightService(provider_router),
        sql_generator=SQLGenerator(provider_router, sql_validator()),
    )


@lru_cache
def proactive_service() -> ProactiveAnalyticsService:
    return ProactiveAnalyticsService(
        database_service(),
        sql_validator(),
        InsightService(ProviderRouter(get_settings())),
    )


@router.get("/health")
def health(database: DatabaseService = Depends(database_service)) -> dict[str, object]:
    return {"status": "ok" if database.health() else "degraded", "database": database.health(), "service": "productlens-api"}


@router.get("/metadata/dataset")
def dataset_metadata(database: DatabaseService = Depends(database_service)) -> dict[str, object]:
    try:
        return database.dataset_metadata()
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/catalog")
def catalog(database: DatabaseService = Depends(database_service)) -> dict[str, object]:
    try:
        metadata = database.dataset_metadata()
        raw_counts = metadata.get("row_counts")
        counts = {str(key): int(value) for key, value in raw_counts.items()} if isinstance(raw_counts, dict) else None
    except DatabaseUnavailable:
        counts = None
    return registry.public_catalog_with_counts(counts)


@router.post("/analytics/kpi")
@router.post("/analytics/compare")
@router.post("/analytics/segment")
def metric_analysis(request: AnalyticsRequest, service: AnalyticsService = Depends(analytics_service)) -> dict[str, object]:
    try:
        return service.metric(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/analytics/feature-adoption", response_model=FeatureAdoptionAnalyticsResponse)
def feature_adoption_analysis(
    request: AnalyticsRequest,
    service: AnalyticsService = Depends(analytics_service),
) -> FeatureAdoptionAnalyticsResponse:
    try:
        return FeatureAdoptionAnalyticsResponse.model_validate(service.feature_adoption(request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/analytics/acquisition", response_model=AcquisitionAnalyticsResponse)
def acquisition_analysis(
    request: AcquisitionRequest,
    service: AnalyticsService = Depends(analytics_service),
) -> AcquisitionAnalyticsResponse:
    try:
        return AcquisitionAnalyticsResponse.model_validate(service.acquisition(request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/analytics/overview", response_model=OverviewAnalyticsResponse)
def overview_analysis(
    request: OverviewRequest,
    service: AnalyticsService = Depends(analytics_service),
) -> OverviewAnalyticsResponse:
    try:
        return OverviewAnalyticsResponse.model_validate(service.overview(request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/analytics/retention", response_model=RetentionAnalyticsResponse)
@router.post("/analytics/cohort", response_model=RetentionAnalyticsResponse)
def retention_analysis(
    request: RetentionRequest,
    service: AnalyticsService = Depends(analytics_service),
) -> RetentionAnalyticsResponse:
    try:
        return RetentionAnalyticsResponse.model_validate(service.retention(request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/analytics/trend")
def trend_analysis(request: AnalyticsRequest, service: AnalyticsService = Depends(analytics_service)) -> dict[str, object]:
    try:
        return service.trend(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/analytics/funnel")
def funnel_analysis(request: FunnelRequest, service: AnalyticsService = Depends(analytics_service)) -> dict[str, object]:
    try:
        return service.funnel(request)
    except (ValueError, DatabaseUnavailable) as exc:
        raise HTTPException(status_code=422 if isinstance(exc, ValueError) else 503, detail=str(exc)) from exc


@router.get("/insights/anomalies", response_model=AnomaliesResponse)
def anomalies(
    period: str = Query(default="last_30_days"),
    limit: int = Query(default=50, ge=1, le=50),
    service: ProactiveAnalyticsService = Depends(proactive_service),
) -> AnomaliesResponse:
    try:
        return service.anomalies(period, limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/insights/pulse", response_model=ProductPulseResponse)
def product_pulse(
    period: str = Query(default="last_30_days"),
    limit: int = Query(default=20, ge=1, le=50),
    service: ProactiveAnalyticsService = Depends(proactive_service),
) -> ProductPulseResponse:
    try:
        return service.pulse(period, limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/reports/weekly/markdown")
def weekly_report_markdown(
    period: str = Query(default="last_week"),
    service: ProactiveAnalyticsService = Depends(proactive_service),
) -> PlainTextResponse:
    try:
        report = service.weekly_report(period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    filename = f"productlens-weekly-report-{report.period.start.isoformat()}.md"
    return PlainTextResponse(
        ProactiveAnalyticsService.to_markdown(report),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/weekly", response_model=WeeklyReportResponse)
def weekly_report(
    period: str = Query(default="last_week"),
    service: ProactiveAnalyticsService = Depends(proactive_service),
) -> WeeklyReportResponse:
    try:
        return service.weekly_report(period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/copilot/analyze", response_model=CopilotResponse)
def copilot_analyze(request: CopilotRequest, pipeline: CopilotPipeline = Depends(copilot_pipeline)) -> CopilotResponse:
    return pipeline.analyze(request)


@router.get("/history")
def history(
    x_productlens_session: str = Header(min_length=20, max_length=128),
    limit: int = Query(default=30, ge=1, le=100),
    settings: Settings = Depends(get_settings),
    database: DatabaseService = Depends(database_service),
) -> list[dict[str, object]]:
    session_hash = hash_session(x_productlens_session, settings.session_hmac_secret.get_secret_value())
    try:
        return database.history(session_hash, limit)
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/history/{query_id}")
def history_item(
    query_id: UUID,
    x_productlens_session: str = Header(min_length=20, max_length=128),
    settings: Settings = Depends(get_settings),
    database: DatabaseService = Depends(database_service),
) -> dict[str, object]:
    session_hash = hash_session(x_productlens_session, settings.session_hmac_secret.get_secret_value())
    try:
        item = database.history_item(session_hash, query_id)
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return item
