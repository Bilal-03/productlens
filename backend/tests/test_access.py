from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.models.contracts import AuthMode, WorkspaceRole
from app.security.access import (
    AccessTokenClaims,
    AccessTokenError,
    Permission,
    create_access_token,
    parse_access_token,
    resolve_access_context,
)

SECRET = "access-test-secret-with-at-least-32-bytes"
SESSION_SECRET = "session-test-secret-with-at-least-32-bytes"
client = TestClient(app)


def claims(
    *, role: WorkspaceRole = WorkspaceRole.ANALYST, expires_at: int | None = None
) -> AccessTokenClaims:
    now = datetime.now(UTC)
    return AccessTokenClaims(
        workspace_id="workspace-acme",
        subject_id="analyst@example.com",
        role=role,
        issued_at=int(now.timestamp()),
        expires_at=expires_at or int((now + timedelta(minutes=5)).timestamp()),
    )


def settings() -> Settings:
    return Settings(
        access_token_secret=SECRET,
        session_hmac_secret=SESSION_SECRET,
    )


def test_signed_access_token_round_trips_and_rejects_tampering() -> None:
    token = create_access_token(claims(), SECRET)
    parsed = parse_access_token(token, SECRET)

    assert parsed.workspace_id == "workspace-acme"
    assert parsed.subject_id == "analyst@example.com"
    assert parsed.role is WorkspaceRole.ANALYST

    with pytest.raises(AccessTokenError, match="signature"):
        parse_access_token(f"{token}x", SECRET)


def test_access_token_rejects_expired_and_future_assertions() -> None:
    expired = create_access_token(claims(expires_at=900), SECRET)
    with pytest.raises(AccessTokenError, match="expired"):
        parse_access_token(expired, SECRET, now=1_000)

    future = AccessTokenClaims(
        workspace_id="workspace-acme",
        subject_id="analyst@example.com",
        role=WorkspaceRole.ANALYST,
        issued_at=2_000,
        expires_at=3_000,
    )
    with pytest.raises(AccessTokenError, match="future"):
        parse_access_token(create_access_token(future, SECRET), SECRET, now=1_000)


def test_role_permissions_and_workspace_session_isolation() -> None:
    viewer = resolve_access_context(
        access_token=create_access_token(claims(role=WorkspaceRole.VIEWER), SECRET),
        session_id="shared-browser-session-123456",
        settings=settings(),
    )
    analyst = resolve_access_context(
        access_token=create_access_token(claims(role=WorkspaceRole.ANALYST), SECRET),
        session_id="shared-browser-session-123456",
        settings=settings(),
    )
    other_workspace_claims = claims().model_copy(update={"workspace_id": "workspace-other"})
    other_workspace = resolve_access_context(
        access_token=create_access_token(other_workspace_claims, SECRET),
        session_id="shared-browser-session-123456",
        settings=settings(),
    )

    assert viewer.auth_mode is AuthMode.SIGNED
    assert viewer.can(Permission.HISTORY_READ)
    assert not viewer.can(Permission.ANALYZE)
    assert analyst.can(Permission.ANALYZE)
    assert analyst.can(Permission.NOTEBOOK_WRITE)
    assert analyst.session_hash != other_workspace.session_hash


def test_anonymous_context_preserves_existing_session_boundary() -> None:
    context = resolve_access_context(
        access_token=None,
        session_id="anonymous-browser-session-123456",
        settings=settings(),
    )

    assert context.auth_mode is AuthMode.ANONYMOUS
    assert context.role is WorkspaceRole.ANALYST
    assert context.session_hash is not None
    assert context.canonical_session_id("anonymous-browser-session-123456") == "anonymous-browser-session-123456"


def test_signed_context_requires_an_explicit_access_secret() -> None:
    token = create_access_token(claims(), SECRET)

    with pytest.raises(AccessTokenError, match="not configured"):
        resolve_access_context(
            access_token=token,
            session_id="signed-browser-session-123456",
            settings=Settings(session_hmac_secret=SESSION_SECRET),
        )


def test_access_context_api_enforces_role_permissions() -> None:
    configured = settings()
    app.dependency_overrides[get_settings] = lambda: configured
    session = "signed-browser-session-123456"
    viewer_token = create_access_token(claims(role=WorkspaceRole.VIEWER), SECRET)
    try:
        context_response = client.get(
            "/api/v1/access/context",
            headers={"X-ProductLens-Access": viewer_token, "X-ProductLens-Session": session},
        )
        blocked_response = client.post(
            "/api/v1/notebook/insights",
            headers={"X-ProductLens-Access": viewer_token, "X-ProductLens-Session": session},
            json={"source_query_id": str(uuid4())},
        )
        invalid_response = client.get(
            "/api/v1/access/context",
            headers={"X-ProductLens-Access": "plx1.invalid.invalid"},
        )
    finally:
        app.dependency_overrides.clear()

    assert context_response.status_code == 200
    assert context_response.json()["workspace_id"] == "workspace-acme"
    assert context_response.json()["role"] == "viewer"
    assert "analytics:read" in context_response.json()["permissions"]
    assert "notebook:write" not in context_response.json()["permissions"]
    assert blocked_response.status_code == 403
    assert invalid_response.status_code == 401
