from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.ai.insights import InsightService
from app.ai.pipeline import CopilotPipeline
from app.ai.planner import QuestionPlanner
from app.ai.providers import ProviderRouter
from app.ai.sql_generation import SQLGenerator
from app.analytics.service import AnalyticsService
from app.config import Settings, get_settings
from app.database.service import DatabaseService, DatabaseUnavailable
from app.models.contracts import (
    AnalyticsRequest,
    CopilotRequest,
    CopilotResponse,
    FunnelRequest,
    RetentionAnalyticsResponse,
    RetentionRequest,
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
def catalog() -> dict[str, object]:
    return registry.public_catalog()


@router.post("/analytics/kpi")
@router.post("/analytics/compare")
@router.post("/analytics/segment")
@router.post("/analytics/feature-adoption")
def metric_analysis(request: AnalyticsRequest, service: AnalyticsService = Depends(analytics_service)) -> dict[str, object]:
    try:
        return service.metric(request)
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
