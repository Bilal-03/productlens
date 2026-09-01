from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from functools import lru_cache
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse, StreamingResponse

from app.ai.insights import InsightService
from app.ai.pipeline import CopilotPipeline
from app.ai.planner import QuestionPlanner
from app.ai.providers import ProviderRouter
from app.ai.sql_generation import SQLGenerator
from app.analytics.advanced import AdvancedAnalyticsService
from app.analytics.experiments import ExperimentAnalyticsService
from app.analytics.proactive import ProactiveAnalyticsService
from app.analytics.service import AnalyticsService
from app.config import Settings, get_settings
from app.connectors.postgres import (
    TenantDatabaseRouter,
    TenantSourceRegistry,
    TenantSourceUnavailable,
)
from app.database.service import DatabaseService, DatabaseUnavailable
from app.models.contracts import (
    AccessContextResponse,
    AcquisitionAnalyticsResponse,
    AcquisitionRequest,
    AdvancedAnalyticsResponse,
    AnalyticsRequest,
    AnomaliesResponse,
    AuthMode,
    ConnectorStatusResponse,
    CopilotRequest,
    CopilotResponse,
    DateRange,
    ExperimentAnalysisResponse,
    ExperimentListResponse,
    FeatureAdoptionAnalyticsResponse,
    FunnelRequest,
    NotebookInsight,
    NotebookResponse,
    NotebookSummaryResponse,
    OverviewAnalyticsResponse,
    OverviewRequest,
    OverviewSummaryResponse,
    ProductPulseResponse,
    RetentionAnalyticsResponse,
    RetentionRequest,
    SaveInsightRequest,
    StreamMetricSnapshot,
    WeeklyReportResponse,
)
from app.notebook.service import NotebookService
from app.security.access import AccessContext, AccessTokenError, Permission, resolve_access_context
from app.security.oidc import OIDCValidator
from app.security.session import hash_session
from app.security.sql_validator import SQLSafetyPolicy, SQLValidator
from app.semantic.registry import registry

router = APIRouter()


@lru_cache
def oidc_token_validator() -> OIDCValidator:
    return OIDCValidator(get_settings())


def _bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token:
        raise AccessTokenError("Malformed authorization header")
    return token.strip() or None


def access_context(
    x_productlens_access: str | None = Header(default=None, max_length=4096),
    x_productlens_session: str | None = Header(default=None, max_length=128),
    authorization: str | None = Header(default=None, max_length=8192),
    settings: Settings = Depends(get_settings),
    oidc_validator: OIDCValidator = Depends(oidc_token_validator),
) -> AccessContext:
    try:
        bearer_token = _bearer_token(authorization)
        if x_productlens_access and bearer_token and x_productlens_access != bearer_token:
            raise AccessTokenError("Conflicting access credentials")
        return resolve_access_context(
            access_token=x_productlens_access or bearer_token,
            session_id=x_productlens_session,
            settings=settings,
            oidc_validator=oidc_validator,
        )
    except AccessTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired workspace access token") from exc


def require_permission(permission: str) -> Callable[[AccessContext], AccessContext]:
    def dependency(context: AccessContext = Depends(access_context)) -> AccessContext:
        if not context.can(permission):
            raise HTTPException(status_code=403, detail="The workspace role does not allow this action")
        return context

    return dependency


def session_hash_for(context: AccessContext, raw_session: str, settings: Settings) -> str:
    return context.session_hash or hash_session(raw_session, settings.session_hmac_secret.get_secret_value())


@lru_cache
def database_service() -> DatabaseService:
    return DatabaseService(get_settings())


@lru_cache
def sql_validator() -> SQLValidator:
    settings = get_settings()
    return SQLValidator(SQLSafetyPolicy(max_rows=settings.max_query_rows))


def tenant_source_registry(settings: Settings = Depends(get_settings)) -> TenantSourceRegistry:
    return TenantSourceRegistry(settings)


def tenant_database_service(
    context: AccessContext = Depends(access_context),
    base_database: DatabaseService = Depends(database_service),
    settings: Settings = Depends(get_settings),
) -> DatabaseService:
    try:
        return TenantDatabaseRouter(settings, base_database).database_for(context)
    except TenantSourceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def analytics_service(
    database: DatabaseService = Depends(tenant_database_service),
    validator: SQLValidator = Depends(sql_validator),
) -> AnalyticsService:
    return AnalyticsService(database, validator)


def copilot_pipeline(
    database: DatabaseService = Depends(tenant_database_service),
    analytics: AnalyticsService = Depends(analytics_service),
    validator: SQLValidator = Depends(sql_validator),
    settings: Settings = Depends(get_settings),
) -> CopilotPipeline:
    provider_router = ProviderRouter(
        settings,
        timeout_seconds=settings.multi_agent_timeout_ms / 1000,
        max_attempts=1,
    )
    return CopilotPipeline(
        settings=settings,
        database=database,
        analytics=analytics,
        planner=QuestionPlanner(),
        validator=validator,
        insights=InsightService(provider_router),
        sql_generator=SQLGenerator(provider_router, validator),
    )


def proactive_service(
    database: DatabaseService = Depends(tenant_database_service),
    settings: Settings = Depends(get_settings),
    validator: SQLValidator = Depends(sql_validator),
) -> ProactiveAnalyticsService:
    report_provider_timeout = settings.report_provider_timeout_ms / 1000 if settings.report_provider_timeout_ms > 0 else None
    return ProactiveAnalyticsService(
        database,
        validator,
        InsightService(
            ProviderRouter(
                settings,
                timeout_seconds=report_provider_timeout,
                max_attempts=1,
            )
        ),
        report_budget_ms=settings.proactive_report_budget_ms,
        report_provider_timeout_ms=settings.report_provider_timeout_ms,
    )


def experiment_service(
    database: DatabaseService = Depends(tenant_database_service),
    validator: SQLValidator = Depends(sql_validator),
) -> ExperimentAnalyticsService:
    return ExperimentAnalyticsService(database, validator)


def advanced_service(
    database: DatabaseService = Depends(tenant_database_service),
    validator: SQLValidator = Depends(sql_validator),
) -> AdvancedAnalyticsService:
    return AdvancedAnalyticsService(database, validator)


def notebook_service(
    database: DatabaseService = Depends(tenant_database_service),
) -> NotebookService:
    return NotebookService(database)


@router.get("/access/context", response_model=AccessContextResponse)
def access_context_info(
    context: AccessContext = Depends(access_context),
    settings: Settings = Depends(get_settings),
) -> AccessContextResponse:
    source = TenantSourceRegistry(settings).configured_status(context)
    return AccessContextResponse(
        workspace_id=context.workspace_id,
        tenant_id=context.tenant_id,
        subject_id=context.subject_id,
        role=context.role,
        auth_mode=context.auth_mode,
        permissions=sorted(context.permissions),
        session_scoped=context.session_hash is not None,
        source_id=source.source_id,
        source_configured=source.configured,
    )


@router.api_route("/health", methods=["GET", "HEAD"])
def health(database: DatabaseService = Depends(database_service)) -> dict[str, object]:
    return {"status": "ok" if database.health() else "degraded", "database": database.health(), "service": "productlens-api"}


@router.get("/metadata/dataset")
def dataset_metadata(
    context: AccessContext = Depends(require_permission(Permission.ANALYTICS_READ)),
    database: DatabaseService = Depends(tenant_database_service),
) -> dict[str, object]:
    try:
        return database.dataset_metadata()
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/catalog")
def catalog(
    context: AccessContext = Depends(require_permission(Permission.ANALYTICS_READ)),
    database: DatabaseService = Depends(tenant_database_service),
) -> dict[str, object]:
    try:
        metadata = database.dataset_metadata()
        raw_counts = metadata.get("row_counts")
        counts = {str(key): int(value) for key, value in raw_counts.items()} if isinstance(raw_counts, dict) else None
    except DatabaseUnavailable:
        counts = None
    return registry.public_catalog_with_counts(counts)


@router.get("/connectors/status", response_model=ConnectorStatusResponse)
def connector_status(
    context: AccessContext = Depends(require_permission(Permission.ANALYTICS_READ)),
    settings: Settings = Depends(get_settings),
    base_database: DatabaseService = Depends(database_service),
) -> ConnectorStatusResponse:
    registry_service = TenantSourceRegistry(settings)
    try:
        source = TenantDatabaseRouter(settings, base_database).status_for(context)
    except TenantSourceUnavailable:
        source = registry_service.configured_status(context)
    return ConnectorStatusResponse(source=source)


@router.post("/analytics/kpi")
@router.post("/analytics/compare")
@router.post("/analytics/segment")
def metric_analysis(
    request: AnalyticsRequest,
    context: AccessContext = Depends(require_permission(Permission.ANALYTICS_READ)),
    service: AnalyticsService = Depends(analytics_service),
) -> dict[str, object]:
    try:
        return service.metric(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/analytics/feature-adoption", response_model=FeatureAdoptionAnalyticsResponse)
def feature_adoption_analysis(
    request: AnalyticsRequest,
    context: AccessContext = Depends(require_permission(Permission.ANALYTICS_READ)),
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
    context: AccessContext = Depends(require_permission(Permission.ANALYTICS_READ)),
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
    context: AccessContext = Depends(require_permission(Permission.ANALYTICS_READ)),
    service: AnalyticsService = Depends(analytics_service),
) -> OverviewAnalyticsResponse:
    try:
        return OverviewAnalyticsResponse.model_validate(service.overview(request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/analytics/overview/summary", response_model=OverviewSummaryResponse)
def overview_summary_analysis(
    request: OverviewRequest,
    context: AccessContext = Depends(require_permission(Permission.ANALYTICS_READ)),
    service: AnalyticsService = Depends(analytics_service),
) -> OverviewSummaryResponse:
    try:
        return OverviewSummaryResponse.model_validate(service.overview_summary(request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/analytics/retention", response_model=RetentionAnalyticsResponse)
@router.post("/analytics/cohort", response_model=RetentionAnalyticsResponse)
def retention_analysis(
    request: RetentionRequest,
    context: AccessContext = Depends(require_permission(Permission.ANALYTICS_READ)),
    service: AnalyticsService = Depends(analytics_service),
) -> RetentionAnalyticsResponse:
    try:
        return RetentionAnalyticsResponse.model_validate(service.retention(request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/analytics/trend")
def trend_analysis(
    request: AnalyticsRequest,
    context: AccessContext = Depends(require_permission(Permission.ANALYTICS_READ)),
    service: AnalyticsService = Depends(analytics_service),
) -> dict[str, object]:
    try:
        return service.trend(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/analytics/funnel")
def funnel_analysis(
    request: FunnelRequest,
    context: AccessContext = Depends(require_permission(Permission.ANALYTICS_READ)),
    service: AnalyticsService = Depends(analytics_service),
) -> dict[str, object]:
    try:
        return service.funnel(request)
    except (ValueError, DatabaseUnavailable) as exc:
        raise HTTPException(status_code=422 if isinstance(exc, ValueError) else 503, detail=str(exc)) from exc


@router.get("/insights/anomalies", response_model=AnomaliesResponse)
def anomalies(
    period: str = Query(default="last_30_days"),
    limit: int = Query(default=50, ge=1, le=50),
    context: AccessContext = Depends(require_permission(Permission.ANALYTICS_READ)),
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
    context: AccessContext = Depends(require_permission(Permission.ANALYTICS_READ)),
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
    context: AccessContext = Depends(require_permission(Permission.ANALYTICS_READ)),
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
    context: AccessContext = Depends(require_permission(Permission.ANALYTICS_READ)),
    service: ProactiveAnalyticsService = Depends(proactive_service),
) -> WeeklyReportResponse:
    try:
        return service.weekly_report(period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _stream_event(event: str, payload: StreamMetricSnapshot) -> str:
    return (
        f"id: {payload.event_id}\n"
        f"event: {event}\n"
        f"data: {json.dumps(payload.model_dump(mode='json'), separators=(',', ':'))}\n\n"
    )


@router.get("/stream/analytics")
def analytics_stream(
    metric: str = Query(default="mau", min_length=2, max_length=64),
    period: str = Query(default="last_30_days"),
    max_events: int = Query(default=3, ge=1, le=5),
    poll_seconds: int | None = Query(default=None, ge=1, le=15),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID", max_length=32),
    context: AccessContext = Depends(require_permission(Permission.ANALYTICS_READ)),
    service: AnalyticsService = Depends(analytics_service),
    database: DatabaseService = Depends(tenant_database_service),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    if metric not in registry.metrics:
        raise HTTPException(status_code=422, detail=f"Unsupported metric: {metric}")
    if period not in {"last_30_days", "last_90_days"}:
        raise HTTPException(status_code=422, detail="Streaming supports last_30_days or last_90_days")
    try:
        starting_id = max(0, int(last_event_id or "0"))
    except ValueError:
        starting_id = 0
    interval = poll_seconds or settings.sse_poll_interval_seconds
    max_duration = settings.sse_max_duration_seconds

    def snapshot_for(version: str, event_id: int, snapshot_type: str) -> StreamMetricSnapshot:
        result = service.metric(AnalyticsRequest(metric=metric, period=period))
        metric_definition = result.get("metric") if isinstance(result, dict) else {}
        if not isinstance(metric_definition, dict):
            metric_definition = {}
        rows = result.get("current") if isinstance(result, dict) else []
        row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
        raw_value = row.get("value")
        period_value = result.get("current_period") if isinstance(result, dict) else None
        period_contract = DateRange.model_validate(period_value) if isinstance(period_value, dict) else None
        value = float(raw_value) if raw_value is not None else None
        return StreamMetricSnapshot(
            type=snapshot_type,
            event_id=event_id,
            generated_at=datetime.now(UTC),
            dataset_version=version,
            source_id=database.source_id,
            tenant_id=context.tenant_id,
            metric=metric,
            metric_label=str(metric_definition.get("label") or metric),
            period=period_contract,
            value=value,
            formatted=_format_stream_value(value, registry.metric(metric).format) if value is not None else None,
        )

    initial_version = database.dataset_version() or "unavailable"
    try:
        initial_snapshot = snapshot_for(initial_version, max(1, starting_id + 1), "snapshot")
    except (DatabaseUnavailable, ValueError) as exc:
        raise HTTPException(status_code=503, detail="The analytics update stream is unavailable") from exc

    def stream() -> Iterator[str]:
        started = time.monotonic()
        event_id = initial_snapshot.event_id
        emitted_updates = 1
        previous_version: str | None = initial_version
        latest: StreamMetricSnapshot | None = initial_snapshot
        yield _stream_event("snapshot", initial_snapshot)
        while emitted_updates < max_events and time.monotonic() - started < max_duration:
            version = database.dataset_version() or "unavailable"
            if version != previous_version:
                try:
                    event_id += 1
                    latest = snapshot_for(version, event_id, "update")
                    previous_version = version
                    emitted_updates += 1
                    yield _stream_event(latest.type, latest)
                except (DatabaseUnavailable, ValueError):
                    break
            elif latest is not None:
                event_id += 1
                heartbeat = latest.model_copy(update={"type": "heartbeat", "event_id": event_id})
                yield _stream_event("heartbeat", heartbeat)
            remaining = max_duration - (time.monotonic() - started)
            if remaining <= 0:
                break
            time.sleep(min(interval, remaining))

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _format_stream_value(value: float, format_name: str) -> str:
    if format_name == "currency":
        return f"${value:,.0f}"
    if format_name == "percentage":
        return f"{value * 100:.1f}%"
    return f"{value:,.0f}"


@router.get("/experiments", response_model=ExperimentListResponse)
def experiments(
    context: AccessContext = Depends(require_permission(Permission.ANALYTICS_READ)),
    service: ExperimentAnalyticsService = Depends(experiment_service),
) -> ExperimentListResponse:
    try:
        return service.list_experiments()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/experiments/{experiment_key}/analysis", response_model=ExperimentAnalysisResponse)
def experiment_analysis(
    experiment_key: str,
    period: str = Query(default="last_90_days"),
    context: AccessContext = Depends(require_permission(Permission.ANALYTICS_READ)),
    service: ExperimentAnalyticsService = Depends(experiment_service),
) -> ExperimentAnalysisResponse:
    try:
        return service.analysis(experiment_key, period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/analytics/advanced", response_model=AdvancedAnalyticsResponse)
def advanced_analytics(
    period: str = Query(default="last_90_days"),
    context: AccessContext = Depends(require_permission(Permission.ANALYTICS_READ)),
    service: AdvancedAnalyticsService = Depends(advanced_service),
) -> AdvancedAnalyticsResponse:
    try:
        return service.report(period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/copilot/analyze", response_model=CopilotResponse)
def copilot_analyze(
    request: CopilotRequest,
    pipeline: CopilotPipeline = Depends(copilot_pipeline),
    context: AccessContext = Depends(require_permission(Permission.ANALYZE)),
) -> CopilotResponse:
    if context.auth_mode is not AuthMode.ANONYMOUS:
        request = request.model_copy(update={"session_id": context.canonical_session_id(request.session_id)})
    return pipeline.analyze(request)


@router.get("/history")
def history(
    x_productlens_session: str = Header(min_length=20, max_length=128),
    limit: int = Query(default=30, ge=1, le=100),
    settings: Settings = Depends(get_settings),
    context: AccessContext = Depends(require_permission(Permission.HISTORY_READ)),
    database: DatabaseService = Depends(tenant_database_service),
) -> list[dict[str, object]]:
    session_hash = session_hash_for(context, x_productlens_session, settings)
    try:
        return database.history(session_hash, limit)
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/history/{query_id}")
def history_item(
    query_id: UUID,
    x_productlens_session: str = Header(min_length=20, max_length=128),
    settings: Settings = Depends(get_settings),
    context: AccessContext = Depends(require_permission(Permission.HISTORY_READ)),
    database: DatabaseService = Depends(tenant_database_service),
) -> dict[str, object]:
    session_hash = session_hash_for(context, x_productlens_session, settings)
    try:
        item = database.history_item(session_hash, query_id)
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return item


@router.get("/notebook/insights", response_model=NotebookResponse)
def notebook_insights(
    x_productlens_session: str = Header(min_length=20, max_length=128),
    limit: int = Query(default=50, ge=1, le=50),
    settings: Settings = Depends(get_settings),
    context: AccessContext = Depends(require_permission(Permission.NOTEBOOK_READ)),
    service: NotebookService = Depends(notebook_service),
) -> NotebookResponse:
    session_hash = session_hash_for(context, x_productlens_session, settings)
    try:
        return NotebookResponse(insights=service.list(session_hash, limit), limit=limit)
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/notebook/summary", response_model=NotebookSummaryResponse)
def notebook_summary(
    x_productlens_session: str = Header(min_length=20, max_length=128),
    limit: int = Query(default=50, ge=1, le=50),
    settings: Settings = Depends(get_settings),
    context: AccessContext = Depends(require_permission(Permission.NOTEBOOK_READ)),
    service: NotebookService = Depends(notebook_service),
) -> NotebookSummaryResponse:
    session_hash = session_hash_for(context, x_productlens_session, settings)
    try:
        summary = service.summary(session_hash, limit)
        return NotebookSummaryResponse(
            summary=summary,
            insight_count=summary.methodology.source_insight_count if summary else 0,
            limit=limit,
        )
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/notebook/insights", response_model=NotebookInsight, status_code=201)
def save_notebook_insight(
    request: SaveInsightRequest,
    x_productlens_session: str = Header(min_length=20, max_length=128),
    settings: Settings = Depends(get_settings),
    context: AccessContext = Depends(require_permission(Permission.NOTEBOOK_WRITE)),
    service: NotebookService = Depends(notebook_service),
) -> NotebookInsight:
    session_hash = session_hash_for(context, x_productlens_session, settings)
    try:
        return service.save(session_hash, request.source_query_id, request.title)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.delete("/notebook/insights/{insight_id}", status_code=204)
def delete_notebook_insight(
    insight_id: UUID,
    x_productlens_session: str = Header(min_length=20, max_length=128),
    settings: Settings = Depends(get_settings),
    context: AccessContext = Depends(require_permission(Permission.NOTEBOOK_DELETE)),
    service: NotebookService = Depends(notebook_service),
) -> None:
    session_hash = session_hash_for(context, x_productlens_session, settings)
    try:
        deleted = service.delete(session_hash, insight_id)
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Saved insight not found")
