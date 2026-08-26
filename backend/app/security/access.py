"""Provider-neutral signed workspace access context and RBAC policy."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import Settings
from app.models.contracts import AuthMode, WorkspaceRole
from app.security.session import hash_session

ACCESS_TOKEN_VERSION = "plx1"


class Permission:
    ANALYTICS_READ = "analytics:read"
    ANALYZE = "analytics:analyze"
    HISTORY_READ = "history:read"
    NOTEBOOK_READ = "notebook:read"
    NOTEBOOK_WRITE = "notebook:write"
    NOTEBOOK_DELETE = "notebook:delete"
    WORKSPACE_ADMIN = "workspace:admin"


class AccessTokenError(ValueError):
    """Raised when a signed workspace assertion cannot be trusted."""


class AccessTokenClaims(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    workspace_id: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    subject_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:@+-]*$")
    role: WorkspaceRole
    expires_at: int = Field(gt=0)
    issued_at: int | None = Field(default=None, gt=0)


@dataclass(frozen=True)
class AccessContext:
    workspace_id: str
    subject_id: str
    role: WorkspaceRole
    auth_mode: AuthMode
    session_hash: str | None
    permissions: frozenset[str]

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def canonical_session_id(self, raw_session_id: str | None) -> str:
        if self.auth_mode is AuthMode.ANONYMOUS:
            return raw_session_id or ""
        source = raw_session_id or "default"
        digest = hashlib.sha256(
            f"{self.workspace_id}\0{self.subject_id}\0{source}".encode()
        ).hexdigest()
        return f"workspace-session-{digest}"


def create_access_token(claims: AccessTokenClaims, secret: str) -> str:
    """Create an assertion for a trusted SSO gateway or test fixture.

    This function is intentionally not exposed through an HTTP endpoint. Token
    issuance belongs to the identity provider or deployment gateway.
    """

    payload = _encode_json(claims.model_dump(mode="json", exclude_none=True))
    signing_input = f"{ACCESS_TOKEN_VERSION}.{payload}"
    signature = _b64encode(hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest())
    return f"{signing_input}.{signature}"


def parse_access_token(token: str, secret: str, *, now: int | None = None) -> AccessTokenClaims:
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != ACCESS_TOKEN_VERSION or not parts[1] or not parts[2]:
        raise AccessTokenError("Malformed access token")

    signing_input = f"{parts[0]}.{parts[1]}"
    expected = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    try:
        supplied = _b64decode(parts[2])
    except ValueError as exc:
        raise AccessTokenError("Malformed access token") from exc
    if not hmac.compare_digest(expected, supplied):
        raise AccessTokenError("Invalid access token signature")

    try:
        payload = json.loads(_b64decode(parts[1]))
        if isinstance(payload, dict) and isinstance(payload.get("role"), str):
            payload["role"] = WorkspaceRole(payload["role"])
        claims = AccessTokenClaims.model_validate(payload)
    except (ValueError, TypeError, ValidationError) as exc:
        raise AccessTokenError("Invalid access token claims") from exc

    current_time = int(time.time()) if now is None else now
    if claims.expires_at <= current_time:
        raise AccessTokenError("Access token expired")
    if claims.issued_at is not None and claims.issued_at > current_time + 60:
        raise AccessTokenError("Access token issued in the future")
    return claims


def resolve_access_context(
    *,
    access_token: str | None,
    session_id: str | None,
    settings: Settings,
) -> AccessContext:
    if access_token:
        access_secret = settings.access_token_secret.get_secret_value() if settings.access_token_secret else ""
        if not access_secret:
            raise AccessTokenError("Workspace access is not configured")
        try:
            claims = parse_access_token(
                access_token,
                access_secret,
            )
        except AccessTokenError:
            raise
        canonical_session = AccessContext(
            workspace_id=claims.workspace_id,
            subject_id=claims.subject_id,
            role=claims.role,
            auth_mode=AuthMode.SIGNED,
            session_hash=None,
            permissions=_permissions(claims.role),
        ).canonical_session_id(session_id)
        return AccessContext(
            workspace_id=claims.workspace_id,
            subject_id=claims.subject_id,
            role=claims.role,
            auth_mode=AuthMode.SIGNED,
            session_hash=hash_session(canonical_session, settings.session_hmac_secret.get_secret_value()),
            permissions=_permissions(claims.role),
        )

    session_hash = (
        hash_session(session_id, settings.session_hmac_secret.get_secret_value())
        if session_id
        else None
    )
    return AccessContext(
        workspace_id="anonymous-demo",
        subject_id="anonymous-demo",
        role=WorkspaceRole.ANALYST,
        auth_mode=AuthMode.ANONYMOUS,
        session_hash=session_hash,
        permissions=frozenset({
            Permission.ANALYTICS_READ,
            Permission.ANALYZE,
            Permission.HISTORY_READ,
            Permission.NOTEBOOK_READ,
            Permission.NOTEBOOK_WRITE,
            Permission.NOTEBOOK_DELETE,
        }),
    )


def _permissions(role: WorkspaceRole) -> frozenset[str]:
    permissions = {Permission.ANALYTICS_READ, Permission.HISTORY_READ, Permission.NOTEBOOK_READ}
    if role in {WorkspaceRole.ANALYST, WorkspaceRole.ADMIN}:
        permissions.update({Permission.ANALYZE, Permission.NOTEBOOK_WRITE, Permission.NOTEBOOK_DELETE})
    if role is WorkspaceRole.ADMIN:
        permissions.add(Permission.WORKSPACE_ADMIN)
    return frozenset(permissions)


def _encode_json(value: dict[str, Any]) -> str:
    return _b64encode(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    try:
        encoded = value.encode("ascii")
        padded = encoded + b"=" * (-len(encoded) % 4)
        return base64.b64decode(padded, altchars=b"-_", validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise ValueError("Invalid base64url value") from exc
