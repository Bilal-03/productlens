"""Small, server-configured PostgreSQL connector for tenant analytics.

The connector deliberately exposes no registration or arbitrary-query API. A
verified workspace claim selects one deployment-configured, read-only source;
all analytics SQL still goes through the existing SQLGlot validator.
"""

from __future__ import annotations

import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from threading import RLock

from sqlalchemy import text

from app.config import Settings, TenantSourceConfig
from app.database.service import DatabaseService
from app.models.contracts import ConnectorSourceStatus
from app.security.access import AccessContext
from app.semantic.registry import registry


class TenantSourceUnavailable(RuntimeError):
    """Raised when a verified tenant has no complete server-side source mapping."""


@dataclass(frozen=True)
class SourceBinding:
    tenant_id: str
    source_id: str
    kind: str
    analytics_url: str
    configured: bool = True


class TenantSourceRegistry:
    """Resolve tenant IDs to fixed source configuration without client input."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def binding_for(self, context: AccessContext) -> SourceBinding:
        if context.tenant_id == "anonymous-demo":
            return SourceBinding(
                tenant_id=context.tenant_id,
                source_id="demo",
                kind="postgres",
                analytics_url=self.settings.analytics_database_url,
            )

        config = self.settings.tenant_source_config.get(context.tenant_id)
        if config is None:
            raise TenantSourceUnavailable(
                f"No analytics source is configured for workspace '{context.workspace_id}'"
            )
        url = self._url_for(config)
        if not url:
            raise TenantSourceUnavailable(
                f"The analytics source for workspace '{context.workspace_id}' is not configured"
            )
        if not _is_postgres_url(url):
            raise TenantSourceUnavailable(
                f"The analytics source for workspace '{context.workspace_id}' must be PostgreSQL"
            )
        return SourceBinding(
            tenant_id=context.tenant_id,
            source_id=config.source_id,
            kind=config.kind,
            analytics_url=url,
        )

    def configured_status(self, context: AccessContext) -> ConnectorSourceStatus:
        try:
            binding = self.binding_for(context)
        except TenantSourceUnavailable as exc:
            config = self.settings.tenant_source_config.get(context.tenant_id)
            return ConnectorSourceStatus(
                source_id=config.source_id if config else "unconfigured",
                tenant_id=context.tenant_id,
                configured=False,
                healthy=False,
                detail=str(exc),
            )
        return ConnectorSourceStatus(
            source_id=binding.source_id,
            tenant_id=binding.tenant_id,
            kind="postgres",
            configured=True,
            healthy=False,
            detail="Source configuration is present; health check pending",
        )

    def _url_for(self, config: TenantSourceConfig) -> str | None:
        value = os.environ.get(config.url_env)
        if value:
            return value.strip()
        local_value = self.settings.tenant_source_urls.get(config.source_id)
        return local_value.get_secret_value().strip() if local_value else None


def _is_postgres_url(value: str) -> bool:
    scheme = value.partition("://")[0].lower()
    return scheme in {"postgres", "postgresql", "postgresql+psycopg"}


@lru_cache(maxsize=32)
def _cached_source_database(
    base_database: DatabaseService,
    tenant_id: str,
    source_id: str,
    analytics_url: str,
) -> DatabaseService:
    """Reuse a tenant-bound engine while a warm serverless process lives."""

    return base_database.with_analytics_source(
        analytics_url,
        source_id=source_id,
        tenant_id=tenant_id,
    )


_STATUS_CACHE: OrderedDict[tuple[int, str, str, str], tuple[float, ConnectorSourceStatus]] = OrderedDict()
_STATUS_CACHE_MAX_ENTRIES = 32
_STATUS_CACHE_LOCK = RLock()


class ReadOnlyPostgresConnector:
    """Bind a ``DatabaseService`` to one fixed analytics PostgreSQL source."""

    REQUIRED_TABLES = tuple(registry.tables)

    def __init__(self, base_database: DatabaseService, binding: SourceBinding) -> None:
        self.binding = binding
        self.database = _cached_source_database(
            base_database,
            binding.tenant_id,
            binding.source_id,
            binding.analytics_url,
        )

    def health(self) -> bool:
        return self.database.analytics_health()

    def contract_ok(self) -> bool:
        try:
            with self.database.analytics_engine.connect() as connection:
                transaction = connection.begin()
                try:
                    connection.execute(text("SET TRANSACTION READ ONLY"))
                    connection.execute(text(f"SET LOCAL statement_timeout = {int(self.database.timeout_ms)}"))
                    for table in self.REQUIRED_TABLES:
                        definition = registry.tables[table]
                        columns = ", ".join(f'"{column}"' for column in definition.columns)
                        connection.execute(text(f"SELECT {columns} FROM analytics.{table} LIMIT 0"))
                finally:
                    transaction.rollback()
            return True
        except Exception:
            return False

    def status(self) -> ConnectorSourceStatus:
        cache_key = (
            id(self.database),
            self.binding.tenant_id,
            self.binding.source_id,
            self.binding.analytics_url,
        )
        now = time.monotonic()
        with _STATUS_CACHE_LOCK:
            cached = _STATUS_CACHE.get(cache_key)
            if cached is not None and cached[0] > now:
                return cached[1].model_copy(deep=True)

        healthy = self.health()
        contract_ok = healthy and self.contract_ok()
        detail = (
            "Read-only PostgreSQL source is healthy and matches the analytics view contract"
            if contract_ok
            else "Source is unavailable or does not expose the required analytics views"
        )
        status = ConnectorSourceStatus(
            source_id=self.binding.source_id,
            tenant_id=self.binding.tenant_id,
            kind="postgres",
            configured=True,
            healthy=contract_ok,
            detail=detail,
        )
        with _STATUS_CACHE_LOCK:
            _STATUS_CACHE[cache_key] = (time.monotonic() + (30 if contract_ok else 5), status)
            _STATUS_CACHE.move_to_end(cache_key)
            while len(_STATUS_CACHE) > _STATUS_CACHE_MAX_ENTRIES:
                _STATUS_CACHE.popitem(last=False)
        return status.model_copy(deep=True)


class TenantDatabaseRouter:
    """Produce a request-scoped database binding for a verified access context."""

    def __init__(self, settings: Settings, base_database: DatabaseService) -> None:
        self.registry = TenantSourceRegistry(settings)
        self.base_database = base_database

    def database_for(self, context: AccessContext) -> DatabaseService:
        binding = self.registry.binding_for(context)
        if context.tenant_id == "anonymous-demo":
            return self.base_database
        return ReadOnlyPostgresConnector(self.base_database, binding).database

    def status_for(self, context: AccessContext) -> ConnectorSourceStatus:
        binding = self.registry.binding_for(context)
        connector = ReadOnlyPostgresConnector(self.base_database, binding)
        return connector.status()
