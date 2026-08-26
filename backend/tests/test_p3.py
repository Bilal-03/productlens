from __future__ import annotations

import json
import time
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.ai.orchestration import AgentOrchestrator
from app.api.routes import analytics_service, database_service, tenant_database_service
from app.config import Settings, TenantSourceConfig, get_settings
from app.connectors.postgres import (
    ReadOnlyPostgresConnector,
    TenantDatabaseRouter,
    TenantSourceRegistry,
    TenantSourceUnavailable,
)
from app.database.service import DatabaseService, DatabaseUnavailable
from app.main import app
from app.models.contracts import AnalysisMode, AuthMode, DateRange, WorkspaceRole
from app.security.access import AccessContext, AccessTokenClaims, Permission, create_access_token


def tenant_context(tenant_id: str = "workspace-acme") -> AccessContext:
    return AccessContext(
        workspace_id=tenant_id,
        tenant_id=tenant_id,
        subject_id="user-123",
        role=WorkspaceRole.ANALYST,
        auth_mode=AuthMode.OIDC,
        session_hash="session-hash",
        permissions=frozenset({Permission.ANALYTICS_READ, Permission.ANALYZE}),
    )


def tenant_settings() -> Settings:
    return Settings(
        tenant_source_config={
            "workspace-acme": TenantSourceConfig(
                source_id="acme-postgres",
                url_env="TENANT_ACME_DATABASE_URL",
            )
        },
        tenant_source_urls={
            "acme-postgres": SecretStr("postgresql+psycopg://reader:secret@example.test:5432/acme")
        },
    )


def test_tenant_registry_uses_only_server_side_source_mapping() -> None:
    registry = TenantSourceRegistry(tenant_settings())

    binding = registry.binding_for(tenant_context())

    assert binding.tenant_id == "workspace-acme"
    assert binding.source_id == "acme-postgres"
    assert binding.analytics_url.endswith("/acme")
    assert registry.configured_status(tenant_context()).configured is True

    with pytest.raises(TenantSourceUnavailable, match="No analytics source"):
        registry.binding_for(tenant_context("workspace-missing"))

    invalid_settings = tenant_settings().model_copy(
        update={
            "tenant_source_urls": {
                "acme-postgres": SecretStr("sqlite:///not-a-postgres-source")
            }
        }
    )
    with pytest.raises(TenantSourceUnavailable, match="must be PostgreSQL"):
        TenantSourceRegistry(invalid_settings).binding_for(tenant_context())


def test_tenant_registry_prefers_server_environment_over_local_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TENANT_ACME_DATABASE_URL", "postgresql://reader:secret@example.test:5432/deployed")

    binding = TenantSourceRegistry(tenant_settings()).binding_for(tenant_context())

    assert binding.analytics_url.endswith("/deployed")


def test_tenant_router_binds_database_to_verified_tenant() -> None:
    captured: dict[str, str] = {}

    class BoundDatabase:
        source_id = "acme-postgres"
        tenant_id = "workspace-acme"

    class BaseDatabase:
        def with_analytics_source(self, url: str, *, source_id: str, tenant_id: str) -> BoundDatabase:
            captured.update(url=url, source_id=source_id, tenant_id=tenant_id)
            return BoundDatabase()

    database = TenantDatabaseRouter(tenant_settings(), BaseDatabase()).database_for(tenant_context())  # type: ignore[arg-type]

    assert database.source_id == "acme-postgres"
    assert database.tenant_id == "workspace-acme"
    assert captured == {
        "url": "postgresql+psycopg://reader:secret@example.test:5432/acme",
        "source_id": "acme-postgres",
        "tenant_id": "workspace-acme",
    }


def test_external_cache_namespace_contains_tenant_and_source() -> None:
    first = DatabaseService.__new__(DatabaseService)
    first.tenant_id = "workspace-a"
    first.source_id = "shared-source"
    second = DatabaseService.__new__(DatabaseService)
    second.tenant_id = "workspace-b"
    second.source_id = "shared-source"

    assert first._cache_namespace("weekly-report") != second._cache_namespace("weekly-report")
    assert len(first._cache_namespace("weekly-report")) == 64


class FakeTransaction:
    def rollback(self) -> None:
        return None


class FakeConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def begin(self) -> FakeTransaction:
        return FakeTransaction()

    def execute(self, statement: Any) -> SimpleNamespace:
        self.statements.append(str(statement))
        return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: []))


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    @contextmanager
    def connect(self):
        yield self.connection


def test_postgres_connector_health_checks_are_read_only_and_contract_bound() -> None:
    engine = FakeEngine()

    class BoundDatabase:
        timeout_ms = 5_000
        analytics_engine = engine

        def analytics_health(self) -> bool:
            return True

    class BaseDatabase:
        def with_analytics_source(self, url: str, *, source_id: str, tenant_id: str) -> BoundDatabase:
            del url, source_id, tenant_id
            return BoundDatabase()

    connector = ReadOnlyPostgresConnector(
        BaseDatabase(),  # type: ignore[arg-type]
        TenantSourceRegistry(tenant_settings()).binding_for(tenant_context()),
    )

    assert connector.contract_ok() is True
    assert any("SET TRANSACTION READ ONLY" in statement for statement in engine.connection.statements)
    assert any('SELECT "user_id"' in statement for statement in engine.connection.statements)
    status = connector.status()
    assert status.healthy is True
    assert status.read_only is True


class StreamDatabase:
    source_id = "demo"
    tenant_id = "anonymous-demo"

    def dataset_version(self) -> str:
        return "demo-v1"


class StreamAnalytics:
    def metric(self, request: Any) -> dict[str, object]:
        assert request.metric == "mau"
        assert request.period == "last_30_days"
        return {
            "metric": {"label": "Monthly Active Users"},
            "current_period": DateRange(
                start="2026-07-25", end="2026-08-24", label="Last 30 Days"
            ).model_dump(mode="json"),
            "current": [{"value": 42}],
        }


def test_stream_route_returns_bounded_sse_snapshot_and_resumes_event_ids() -> None:
    app.dependency_overrides[analytics_service] = lambda: StreamAnalytics()  # type: ignore[assignment]
    app.dependency_overrides[tenant_database_service] = lambda: StreamDatabase()  # type: ignore[assignment]
    client = TestClient(app)
    try:
        response = client.get(
            "/api/v1/stream/analytics",
            params={"metric": "mau", "period": "last_30_days", "max_events": 1},
            headers={"Last-Event-ID": "7"},
        )
        invalid = client.get(
            "/api/v1/stream/analytics",
            params={"metric": "not-a-metric", "max_events": 1},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: 8\n" in response.text
    assert "event: snapshot\n" in response.text
    data_line = next(line for line in response.text.splitlines() if line.startswith("data: "))
    payload = json.loads(data_line[6:])
    assert payload["type"] == "snapshot"
    assert payload["source_id"] == "demo"
    assert payload["value"] == 42.0
    assert invalid.status_code == 422


def test_stream_route_returns_protected_error_when_initial_snapshot_fails() -> None:
    class FailingAnalytics:
        def metric(self, request: Any) -> dict[str, object]:
            del request
            raise DatabaseUnavailable("source down")

    app.dependency_overrides[analytics_service] = lambda: FailingAnalytics()  # type: ignore[assignment]
    app.dependency_overrides[tenant_database_service] = lambda: StreamDatabase()  # type: ignore[assignment]
    client = TestClient(app)
    try:
        response = client.get("/api/v1/stream/analytics", params={"max_events": 1})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503


def test_authenticated_analytics_fail_closed_when_tenant_source_is_missing() -> None:
    secret = "tenant-test-secret-with-at-least-32-bytes"
    settings = Settings(access_token_secret=SecretStr(secret))
    token = create_access_token(
        AccessTokenClaims(
            workspace_id="workspace-missing",
            subject_id="user-123",
            role=WorkspaceRole.ANALYST,
            issued_at=int(time.time()),
            expires_at=int(time.time()) + 300,
        ),
        secret,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[database_service] = lambda: object()  # type: ignore[assignment]
    client = TestClient(app)
    try:
        response = client.get(
            "/api/v1/metadata/dataset",
            headers={"X-ProductLens-Access": token},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert "No analytics source" in response.json()["detail"]


def test_orchestrator_exposes_only_fixed_bounded_stages() -> None:
    orchestrator = AgentOrchestrator(enabled=True, timeout_ms=10_000, mode=AnalysisMode.QUICK)
    for name in ("planner", "analyst", "evidence"):
        started = orchestrator.start(name)
        orchestrator.complete(name, started)

    result = orchestrator.finish()

    assert [agent.name for agent in result.agents] == ["planner", "analyst", "evidence"]
    assert all(agent.status == "completed" for agent in result.agents)
    assert result.handoffs == 2
    assert result.bounded is True
    assert orchestrator.capabilities("analyst") == ("run_governed_analytics",)
    assert set(result.model_dump()) == {"enabled", "mode", "agents", "handoffs", "fallback", "bounded"}

    with pytest.raises(ValueError, match="fixed planner"):
        orchestrator.start("autonomous-researcher")


def test_orchestrator_marks_budget_fallback_without_expanding_capabilities() -> None:
    orchestrator = AgentOrchestrator(
        enabled=True,
        timeout_ms=1_000,
        mode=AnalysisMode.DEEP,
        started_at=time.perf_counter() - 2,
    )
    started = orchestrator.start("evidence")
    assert orchestrator.within_budget() is False
    orchestrator.complete("evidence", started, fallback=True)

    result = orchestrator.finish()

    assert result.fallback is True
    assert result.agents[-1].status == "fallback"
    assert result.handoffs == 2
