from __future__ import annotations

import hashlib
import json
import os
import time
from collections import OrderedDict
from copy import deepcopy
from datetime import UTC, date, datetime
from threading import Lock, RLock
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import NullPool

from app.analytics.time_ranges import DATASET_AS_OF
from app.config import Settings
from app.models.contracts import SQLValidation


class DatabaseUnavailable(RuntimeError):
    pass


# Vercel may reuse a warm Python process, but the operational result cache is
# still the source of truth across processes. This small local layer removes
# repeated app-database round trips during a single overview/report fan-out.
_MEMORY_CACHE_MAX_ENTRIES = 128
_MEMORY_CACHE: OrderedDict[tuple[int, str, str], tuple[float, dict[str, Any]]] = OrderedDict()
_MEMORY_CACHE_LOCK = RLock()


class DatabaseService:
    def __init__(
        self,
        settings: Settings,
        *,
        analytics_database_url: str | None = None,
        source_id: str = "demo",
        tenant_id: str = "anonymous-demo",
        app_engine: Engine | None = None,
    ) -> None:
        self.settings = settings
        self.source_id = source_id
        self.tenant_id = tenant_id
        # Supabase transaction poolers do not support server-side prepared
        # statements. Disabling preparation is safe for direct/session URLs
        # too and keeps the same runtime configuration portable to Vercel.
        kwargs: dict[str, Any] = {"pool_pre_ping": True, "connect_args": {"prepare_threshold": None}}
        pool_mode = getattr(settings, "db_pool_class", "auto")
        is_serverless = (
            pool_mode == "null"
            or (
                pool_mode == "auto"
                and (
                    settings.environment == "serverless"
                    or os.environ.get("VERCEL") == "1"
                    or os.environ.get("AWS_LAMBDA_FUNCTION_NAME") is not None
                )
            )
        )
        if is_serverless:
            kwargs["poolclass"] = NullPool
        else:
            kwargs["pool_size"] = getattr(settings, "db_pool_size", 10)
            kwargs["max_overflow"] = getattr(settings, "db_max_overflow", 5)
            kwargs["pool_recycle"] = getattr(settings, "db_pool_recycle_seconds", 1800)
        self.app_engine: Engine = app_engine or create_engine(
            self._normalize_postgres_url(settings.app_database_url), **kwargs
        )
        self.analytics_engine: Engine = create_engine(
            self._normalize_postgres_url(analytics_database_url or settings.analytics_database_url),
            **kwargs,
        )
        self.timeout_ms = settings.query_timeout_ms
        self._resolved_dataset_as_of: date | None = None
        self._dataset_as_of_lock = Lock()
        self._dataset_version_cache: tuple[str, float] | None = None
        self._dataset_version_lock = Lock()

    def with_analytics_source(
        self,
        analytics_database_url: str,
        *,
        source_id: str,
        tenant_id: str = "anonymous-demo",
    ) -> DatabaseService:
        """Create a source-bound service while sharing the operational engine."""

        return DatabaseService(
            self.settings,
            analytics_database_url=analytics_database_url,
            source_id=source_id,
            tenant_id=tenant_id,
            app_engine=self.app_engine,
        )

    def health(self) -> bool:
        try:
            with self.app_engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def analytics_health(self) -> bool:
        try:
            self._execute_fixed_readonly("SELECT 1")
            return True
        except Exception:
            return False

    def dataset_metadata(self) -> dict[str, Any]:
        if not self._is_demo_source():
            return self._external_dataset_metadata()
        query = text(
            "SELECT dataset_version, dataset_as_of, seed, profile, generated_at, row_counts "
            "FROM operational.dataset_metadata ORDER BY generated_at DESC LIMIT 1"
        )
        try:
            with self.app_engine.connect() as connection:
                row = connection.execute(query).mappings().first()
            if not row:
                raise DatabaseUnavailable("The dataset has not been seeded")
            return dict(row)
        except DatabaseUnavailable:
            raise
        except Exception as exc:
            raise DatabaseUnavailable("The analytics database is unavailable") from exc

    def dataset_version(self) -> str | None:
        ttl_seconds = max(0, int(getattr(self.settings, "dataset_version_cache_seconds", 5)))
        now = time.monotonic()
        with self._dataset_version_lock:
            cached = self._dataset_version_cache
            if ttl_seconds > 0 and cached is not None and cached[1] > now:
                return cached[0]

            value = self._read_dataset_version()
            if value is None:
                self._dataset_version_cache = None
                return None

            if cached is not None and cached[0] != value:
                # A changed fingerprint makes the previously resolved date
                # unsafe to reuse for relative periods.
                with self._dataset_as_of_lock:
                    self._resolved_dataset_as_of = None
            self._dataset_version_cache = (value, now + ttl_seconds) if ttl_seconds > 0 else None
            return value

    def _read_dataset_version(self) -> str | None:
        if not self._is_demo_source():
            try:
                rows = self._execute_fixed_readonly(
                    """SELECT md5(concat_ws('|',
                       (SELECT count(*)::text FROM analytics.users),
                       (SELECT count(*)::text FROM analytics.sessions),
                       (SELECT count(*)::text FROM analytics.events),
                       (SELECT count(*)::text FROM analytics.subscriptions),
                       (SELECT count(*)::text FROM analytics.transactions),
                       (SELECT count(*)::text FROM analytics.daily_activity),
                       (SELECT count(*)::text FROM analytics.experiments),
                       (SELECT count(*)::text FROM analytics.experiment_assignments),
                       COALESCE((SELECT max(event_timestamp)::text FROM analytics.events), '')
                    )) AS dataset_version"""
                )
                value = rows[0].get("dataset_version") if rows else None
                return f"{self.source_id}:{value}" if value is not None else None
            except Exception:
                return None
        try:
            with self.app_engine.connect() as connection:
                value = connection.execute(
                    text("SELECT dataset_version FROM operational.dataset_metadata ORDER BY generated_at DESC LIMIT 1")
                ).scalar_one_or_none()
            return str(value) if value is not None else None
        except Exception:
            return None

    def dataset_as_of(self) -> date:
        """Return the latest source date used for relative periods."""

        if self._is_demo_source():
            return DATASET_AS_OF
        with self._dataset_as_of_lock:
            if self._resolved_dataset_as_of is not None:
                return self._resolved_dataset_as_of
            try:
                rows = self._execute_fixed_readonly(
                    """SELECT GREATEST(
                        COALESCE((SELECT max(event_timestamp)::date FROM analytics.events), DATE '1970-01-01'),
                        COALESCE((SELECT max(signup_at)::date FROM analytics.users), DATE '1970-01-01'),
                        COALESCE((SELECT max(\"timestamp\")::date FROM analytics.transactions), DATE '1970-01-01')
                    ) AS dataset_as_of"""
                )
                value = rows[0].get("dataset_as_of") if rows else None
                if isinstance(value, datetime):
                    value = value.date()
                if not isinstance(value, date) or value == date(1970, 1, 1):
                    raise DatabaseUnavailable("The external analytics source has no usable data horizon")
                self._resolved_dataset_as_of = value
                return value
            except DatabaseUnavailable:
                raise
            except Exception as exc:
                raise DatabaseUnavailable("The external analytics source is unavailable") from exc

    def cache_get(self, cache_key: str, dataset_version: str) -> dict[str, Any] | None:
        statement = text(
            """SELECT payload, GREATEST(EXTRACT(EPOCH FROM (expires_at - now())), 0) AS ttl_remaining
               FROM operational.result_cache
               WHERE cache_key=:cache_key AND dataset_version=:dataset_version AND expires_at > now()"""
        )
        namespaced_key = self._cache_namespace(cache_key)
        memory_key = (id(self.app_engine), namespaced_key, dataset_version)
        with _MEMORY_CACHE_LOCK:
            memory_entry = _MEMORY_CACHE.get(memory_key)
            if memory_entry is not None:
                expires_at, payload = memory_entry
                if expires_at > time.monotonic():
                    _MEMORY_CACHE.move_to_end(memory_key)
                    return deepcopy(payload)
                del _MEMORY_CACHE[memory_key]
        try:
            with self.app_engine.connect() as connection:
                row = connection.execute(
                    statement,
                    {"cache_key": namespaced_key, "dataset_version": dataset_version},
                ).mappings().first()
            if not row:
                return None
            value = row.get("payload")
            ttl_remaining = float(row.get("ttl_remaining") or 0)
            if not isinstance(value, dict) or ttl_remaining <= 0:
                return None
            self._memory_cache_put(memory_key, value, ttl_remaining)
            return deepcopy(value)
        except Exception:
            return None

    def cache_put(self, cache_key: str, dataset_version: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        namespaced_key = self._cache_namespace(cache_key)
        memory_key = (id(self.app_engine), namespaced_key, dataset_version)
        self._memory_cache_put(memory_key, payload, ttl_seconds)
        statement = text(
            """INSERT INTO operational.result_cache (cache_key, dataset_version, payload, expires_at)
               VALUES (:cache_key, :dataset_version, CAST(:payload AS jsonb), now() + (:ttl_seconds * interval '1 second'))
               ON CONFLICT (cache_key) DO UPDATE SET dataset_version=EXCLUDED.dataset_version,
                 payload=EXCLUDED.payload, expires_at=EXCLUDED.expires_at"""
        )
        try:
            with self.app_engine.begin() as connection:
                connection.execute(
                    statement,
                    {
                        "cache_key": namespaced_key,
                        "dataset_version": dataset_version,
                        "payload": json.dumps(payload, default=str),
                        "ttl_seconds": ttl_seconds,
                    },
                )
        except Exception:
            pass

    @staticmethod
    def _memory_cache_put(
        memory_key: tuple[int, str, str], payload: dict[str, Any], ttl_seconds: float
    ) -> None:
        if ttl_seconds <= 0:
            return
        with _MEMORY_CACHE_LOCK:
            _MEMORY_CACHE[memory_key] = (time.monotonic() + ttl_seconds, deepcopy(payload))
            _MEMORY_CACHE.move_to_end(memory_key)
            while len(_MEMORY_CACHE) > _MEMORY_CACHE_MAX_ENTRIES:
                _MEMORY_CACHE.popitem(last=False)

    def _cache_namespace(self, cache_key: str) -> str:
        if self._is_demo_source():
            return cache_key
        # result_cache.cache_key is a fixed 64-character hash. Namespace at
        # the database boundary so a shared operational store cannot return a
        # response calculated from another tenant's source.
        return hashlib.sha256(
            f"{self.tenant_id}:{self.source_id}:{cache_key}".encode()
        ).hexdigest()

    def _is_demo_source(self) -> bool:
        """Keep the public demo namespace distinct from every tenant source."""

        return self.tenant_id == "anonymous-demo" and self.source_id == "demo"

    def _external_dataset_metadata(self) -> dict[str, Any]:
        query = text(
            """SELECT
              (SELECT count(*) FROM analytics.users)::int AS users,
              (SELECT count(*) FROM analytics.sessions)::int AS sessions,
              (SELECT count(*) FROM analytics.events)::int AS events,
              (SELECT count(*) FROM analytics.subscriptions)::int AS subscriptions,
              (SELECT count(*) FROM analytics.transactions)::int AS transactions,
              COALESCE((SELECT max(event_timestamp)::date FROM analytics.events), CURRENT_DATE) AS dataset_as_of
            """
        )
        try:
            rows = self._execute_fixed_readonly(query.text)
            if not rows:
                raise DatabaseUnavailable("The external analytics source returned no metadata")
            row = rows[0]
            source_as_of = row.get("dataset_as_of")
            if isinstance(source_as_of, datetime):
                source_as_of = source_as_of.date()
            if isinstance(source_as_of, date):
                with self._dataset_as_of_lock:
                    self._resolved_dataset_as_of = source_as_of
            version = self.dataset_version()
            if version is None:
                raise DatabaseUnavailable("The external analytics source has no dataset fingerprint")
            return {
                "dataset_version": version,
                "dataset_as_of": row["dataset_as_of"],
                "seed": 0,
                "profile": "external-postgres",
                "generated_at": datetime.now(UTC),
                "row_counts": {key: int(row[key]) for key in ("users", "sessions", "events", "subscriptions", "transactions")},
                "scenario_parameters": {},
            }
        except DatabaseUnavailable:
            raise
        except Exception as exc:
            raise DatabaseUnavailable("The external analytics source is unavailable") from exc

    def _execute_fixed_readonly(self, statement: str) -> list[dict[str, Any]]:
        """Run a server-owned probe in a read-only, timeout-bounded transaction."""

        with self.analytics_engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("SET TRANSACTION READ ONLY"))
                connection.execute(text(f"SET LOCAL statement_timeout = {int(self.timeout_ms)}"))
                result = connection.execute(text(statement))
                return [dict(row) for row in result.mappings().all()]
            finally:
                transaction.rollback()

    @staticmethod
    def _normalize_postgres_url(url: str) -> str:
        normalized = url.strip()
        if normalized.startswith("postgresql://"):
            return "postgresql+psycopg://" + normalized.removeprefix("postgresql://")
        if normalized.startswith("postgres://"):
            return "postgresql+psycopg://" + normalized.removeprefix("postgres://")
        return normalized

    def execute_readonly(self, validation: SQLValidation) -> tuple[list[dict[str, Any]], float]:
        if not validation.valid or not validation.normalized_query:
            raise ValueError("Only validated SQL can be executed")
        started = time.perf_counter()
        try:
            with self.analytics_engine.connect() as connection:
                transaction = connection.begin()
                try:
                    connection.execute(text("SET TRANSACTION READ ONLY"))
                    connection.execute(text(f"SET LOCAL statement_timeout = {int(self.timeout_ms)}"))
                    result = connection.execute(text(validation.normalized_query))
                    rows = [dict(row) for row in result.mappings().all()]
                finally:
                    transaction.rollback()
        except Exception as exc:
            raise DatabaseUnavailable("The validated analytics query could not be executed") from exc
        return rows, (time.perf_counter() - started) * 1000

    def audit(
        self,
        *,
        query_id: UUID,
        session_hash: str,
        question: str,
        generated_sql: str | None,
        validation: SQLValidation,
        execution_status: str | None,
        execution_ms: float | None,
        row_count: int | None,
        error_code: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        statement = text(
            """INSERT INTO operational.query_audit
            (query_id, session_hash, question, generated_sql, validation_status, execution_status,
             validation_errors, execution_ms, row_count, error_code, provider, model,
             input_tokens, output_tokens)
            VALUES (:query_id, :session_hash, :question, :generated_sql, :validation_status,
                    :execution_status, CAST(:validation_errors AS jsonb), :execution_ms, :row_count,
                    :error_code, :provider, :model, :input_tokens, :output_tokens)"""
        )
        with self.app_engine.begin() as connection:
            connection.execute(
                statement,
                {
                    "query_id": query_id,
                    "session_hash": session_hash,
                    "question": question,
                    "generated_sql": generated_sql,
                    "validation_status": "accepted" if validation.valid else "rejected",
                    "execution_status": execution_status,
                    "validation_errors": json.dumps(validation.errors),
                    "execution_ms": execution_ms,
                    "row_count": row_count,
                    "error_code": error_code,
                    "provider": provider,
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
            )

    def save_history(self, payload: dict[str, Any]) -> None:
        statement = text(
            """INSERT INTO operational.query_history
            (query_id, session_hash, question, mode, intent, metric, generated_sql, response,
             chart_spec, provider, latency_ms, status, error_code)
            VALUES (:query_id, :session_hash, :question, :mode, :intent, :metric, :generated_sql,
                    CAST(:response AS jsonb), CAST(:chart_spec AS jsonb), :provider, :latency_ms,
                    :status, :error_code)"""
        )
        serialized = {
            **payload,
            "response": json.dumps(payload.get("response")),
            "chart_spec": json.dumps(payload.get("chart_spec")),
        }
        with self.app_engine.begin() as connection:
            connection.execute(statement, serialized)

    def history(self, session_hash: str, limit: int = 30) -> list[dict[str, Any]]:
        statement = text(
            """SELECT query_id, question, mode, intent, metric, response, chart_spec, provider,
                      latency_ms, status, error_code, created_at
               FROM operational.query_history WHERE session_hash = :session_hash
               ORDER BY created_at DESC LIMIT :limit"""
        )
        try:
            with self.app_engine.connect() as connection:
                return [dict(row) for row in connection.execute(statement, {"session_hash": session_hash, "limit": limit}).mappings()]
        except Exception as exc:
            raise DatabaseUnavailable("The history database is unavailable") from exc

    def history_item(self, session_hash: str, query_id: UUID) -> dict[str, Any] | None:
        statement = text(
            "SELECT response FROM operational.query_history WHERE session_hash=:session_hash AND query_id=:query_id"
        )
        try:
            with self.app_engine.connect() as connection:
                row = connection.execute(statement, {"session_hash": session_hash, "query_id": query_id}).mappings().first()
        except Exception as exc:
            raise DatabaseUnavailable("The history database is unavailable") from exc
        if not row or not row["response"]:
            return None
        response = row["response"]
        if isinstance(response, str):
            try:
                parsed = json.loads(response)
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
        return dict(response) if isinstance(response, dict) else None

    def insert_notebook_insight(
        self,
        *,
        session_hash: str,
        source_query_id: UUID,
        title: str,
        response: dict[str, Any],
    ) -> dict[str, Any]:
        statement = text(
            """INSERT INTO operational.saved_insights
               (insight_id, session_hash, source_query_id, title, response)
               VALUES (:insight_id, :session_hash, :source_query_id, :title, CAST(:response AS jsonb))
               ON CONFLICT (session_hash, source_query_id)
               DO UPDATE SET title=EXCLUDED.title, response=EXCLUDED.response, created_at=now()
               RETURNING insight_id, source_query_id, title, response, created_at"""
        )
        try:
            with self.app_engine.begin() as connection:
                row = connection.execute(
                    statement,
                    {
                        "insight_id": uuid4(),
                        "session_hash": session_hash,
                        "source_query_id": source_query_id,
                        "title": title,
                        "response": json.dumps(response),
                    },
                ).mappings().one()
            return dict(row)
        except Exception as exc:
            raise DatabaseUnavailable("The notebook database is unavailable") from exc

    def notebook_insights(self, session_hash: str, limit: int = 50) -> list[dict[str, Any]]:
        statement = text(
            """SELECT insight_id, source_query_id, title, response, created_at
               FROM operational.saved_insights
               WHERE session_hash = :session_hash
               ORDER BY created_at DESC, insight_id DESC
               LIMIT :limit"""
        )
        try:
            with self.app_engine.connect() as connection:
                return [
                    dict(row)
                    for row in connection.execute(
                        statement, {"session_hash": session_hash, "limit": limit}
                    ).mappings()
                ]
        except Exception as exc:
            raise DatabaseUnavailable("The notebook database is unavailable") from exc

    def delete_notebook_insight(self, session_hash: str, insight_id: UUID) -> bool:
        statement = text(
            "DELETE FROM operational.saved_insights WHERE session_hash=:session_hash AND insight_id=:insight_id"
        )
        try:
            with self.app_engine.begin() as connection:
                result = connection.execute(statement, {"session_hash": session_hash, "insight_id": insight_id})
            return result.rowcount > 0
        except Exception as exc:
            raise DatabaseUnavailable("The notebook database is unavailable") from exc

    def consume_quota(self, session_hash: str, per_hour: int, global_day: int) -> bool:
        now = datetime.now(UTC)
        hour = now.replace(minute=0, second=0, microsecond=0)
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        checks = [(session_hash, hour, "session_hour", per_hour), ("0" * 64, day, "global_day", global_day)]
        statement = text(
            """INSERT INTO operational.request_quota (quota_key, window_start, window_kind, request_count)
               VALUES (:key, :window, :kind, 1)
               ON CONFLICT (quota_key, window_start, window_kind)
               DO UPDATE SET request_count = operational.request_quota.request_count + 1
                 WHERE operational.request_quota.request_count < :maximum
               RETURNING request_count"""
        )
        try:
            with self.app_engine.begin() as connection:
                for key, window, kind, maximum in checks:
                    count = connection.execute(
                        statement,
                        {"key": key, "window": window, "kind": kind, "maximum": maximum},
                    ).scalar_one_or_none()
                    if count is None:
                        raise RuntimeError("quota exceeded")
            return True
        except RuntimeError:
            return False
        except Exception as exc:
            raise DatabaseUnavailable("The quota database is unavailable") from exc
