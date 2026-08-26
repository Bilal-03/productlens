from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.models.contracts import SQLValidation


class DatabaseUnavailable(RuntimeError):
    pass


class DatabaseService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Supabase transaction poolers do not support server-side prepared
        # statements. Disabling preparation is safe for direct/session URLs
        # too and keeps the same runtime configuration portable to Vercel.
        kwargs: dict[str, Any] = {"pool_pre_ping": True, "connect_args": {"prepare_threshold": None}}
        if settings.environment == "production":
            kwargs["poolclass"] = NullPool
        self.app_engine: Engine = create_engine(settings.app_database_url, **kwargs)
        self.analytics_engine: Engine = create_engine(settings.analytics_database_url, **kwargs)
        self.timeout_ms = settings.query_timeout_ms

    def health(self) -> bool:
        try:
            with self.app_engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def dataset_metadata(self) -> dict[str, Any]:
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
        try:
            with self.app_engine.connect() as connection:
                value = connection.execute(
                    text("SELECT dataset_version FROM operational.dataset_metadata ORDER BY generated_at DESC LIMIT 1")
                ).scalar_one_or_none()
            return str(value) if value is not None else None
        except Exception:
            return None

    def cache_get(self, cache_key: str, dataset_version: str) -> dict[str, Any] | None:
        statement = text(
            """SELECT payload FROM operational.result_cache
               WHERE cache_key=:cache_key AND dataset_version=:dataset_version AND expires_at > now()"""
        )
        try:
            with self.app_engine.connect() as connection:
                value = connection.execute(
                    statement, {"cache_key": cache_key, "dataset_version": dataset_version}
                ).scalar_one_or_none()
            return dict(value) if isinstance(value, dict) else None
        except Exception:
            return None

    def cache_put(self, cache_key: str, dataset_version: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
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
                        "cache_key": cache_key,
                        "dataset_version": dataset_version,
                        "payload": json.dumps(payload, default=str),
                        "ttl_seconds": ttl_seconds,
                    },
                )
        except Exception:
            pass

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
