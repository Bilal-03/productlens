from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.api.routes import oidc_token_validator
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
from app.security.oidc import OIDCValidationError, OIDCValidator

SECRET = "access-test-secret-with-at-least-32-bytes"
SESSION_SECRET = "session-test-secret-with-at-least-32-bytes"
client = TestClient(app)
OIDC_ISSUER = "https://id.example.com"
OIDC_AUDIENCE = "productlens-api"
OIDC_PRIVATE_KEYS = {
    "key-1": rsa.generate_private_key(public_exponent=65537, key_size=2048),
    "key-2": rsa.generate_private_key(public_exponent=65537, key_size=2048),
}


class FakeJWKClient:
    def __init__(self, keys: dict[str, object]) -> None:
        self.keys = keys
        self.requested_kids: list[str] = []

    def get_signing_key_from_jwt(self, token: str) -> SimpleNamespace:
        kid = jwt.get_unverified_header(token)["kid"]
        self.requested_kids.append(kid)
        return SimpleNamespace(key=self.keys[kid].public_key())


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


def oidc_settings() -> Settings:
    return Settings(
        session_hmac_secret=SESSION_SECRET,
        oidc_issuer_url=OIDC_ISSUER,
        oidc_audience=OIDC_AUDIENCE,
        oidc_jwks_url=f"{OIDC_ISSUER}/.well-known/jwks.json",
        oidc_role_groups={
            "admin": ["productlens-admin"],
            "analyst": ["productlens-analyst"],
            "viewer": ["productlens-viewer"],
        },
    )


def oidc_token(*, kid: str = "key-1", groups: list[str] | None = None, **overrides: object) -> str:
    now = int(datetime.now(UTC).timestamp())
    payload: dict[str, object] = {
        "iss": OIDC_ISSUER,
        "aud": OIDC_AUDIENCE,
        "sub": "user-123",
        "exp": now + 300,
        "iat": now,
        "workspace_id": "workspace-acme",
        "groups": groups or ["productlens-analyst"],
    }
    payload.update(overrides)
    return jwt.encode(payload, OIDC_PRIVATE_KEYS[kid], algorithm="RS256", headers={"kid": kid})


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


def test_oidc_validator_checks_claims_and_maps_groups_to_roles() -> None:
    jwks = FakeJWKClient(OIDC_PRIVATE_KEYS)
    validator = OIDCValidator(oidc_settings(), jwks_client=jwks)

    identity = validator.validate(oidc_token(groups=["productlens-viewer", "productlens-admin"]))

    assert identity.subject_id == "user-123"
    assert identity.workspace_id == "workspace-acme"
    assert identity.role is WorkspaceRole.ADMIN
    assert identity.groups == ("productlens-viewer", "productlens-admin")

    with pytest.raises(OIDCValidationError, match="validation failed"):
        validator.validate(oidc_token(iss="https://another-id.example.com"))
    with pytest.raises(OIDCValidationError, match="validation failed"):
        validator.validate(oidc_token(aud="another-api"))
    with pytest.raises(OIDCValidationError, match="validation failed"):
        validator.validate(oidc_token(exp=int(datetime.now(UTC).timestamp()) - 1))
    with pytest.raises(OIDCValidationError, match="validation failed"):
        validator.validate(oidc_token() + "tampered")
    unknown_kid_payload = jwt.decode(oidc_token(), options={"verify_signature": False})
    unknown_kid = jwt.encode(unknown_kid_payload, OIDC_PRIVATE_KEYS["key-1"], algorithm="RS256", headers={"kid": "unknown"})
    with pytest.raises(OIDCValidationError, match="validation failed"):
        validator.validate(unknown_kid)
    missing_workspace_payload = dict(unknown_kid_payload)
    missing_workspace_payload.pop("workspace_id")
    missing_workspace = jwt.encode(missing_workspace_payload, OIDC_PRIVATE_KEYS["key-1"], algorithm="RS256", headers={"kid": "key-1"})
    with pytest.raises(OIDCValidationError, match="workspace"):
        validator.validate(missing_workspace)
    missing_groups_payload = dict(unknown_kid_payload)
    missing_groups_payload.pop("groups")
    missing_groups = jwt.encode(missing_groups_payload, OIDC_PRIVATE_KEYS["key-1"], algorithm="RS256", headers={"kid": "key-1"})
    with pytest.raises(OIDCValidationError, match="groups"):
        validator.validate(missing_groups)
    with pytest.raises(OIDCValidationError, match="do not map"):
        validator.validate(oidc_token(groups=["unmapped-group"]))


def test_oidc_jwks_client_receives_rotated_key_ids() -> None:
    jwks = FakeJWKClient(OIDC_PRIVATE_KEYS)
    validator = OIDCValidator(oidc_settings(), jwks_client=jwks)

    validator.validate(oidc_token(kid="key-1"))
    rotated = validator.validate(oidc_token(kid="key-2", groups=["productlens-viewer"]))

    assert rotated.role is WorkspaceRole.VIEWER
    assert jwks.requested_kids == ["key-1", "key-2"]


def test_oidc_bearer_context_is_tenant_scoped_and_exposes_oidc_mode() -> None:
    configured = oidc_settings()
    validator = OIDCValidator(configured, jwks_client=FakeJWKClient(OIDC_PRIVATE_KEYS))
    app.dependency_overrides[get_settings] = lambda: configured
    app.dependency_overrides[oidc_token_validator] = lambda: validator
    try:
        response = client.get(
            "/api/v1/access/context",
            headers={"Authorization": f"Bearer {oidc_token()}"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["auth_mode"] == "oidc"
    assert response.json()["workspace_id"] == "workspace-acme"
    assert response.json()["tenant_id"] == "workspace-acme"
    assert response.json()["role"] == "analyst"
