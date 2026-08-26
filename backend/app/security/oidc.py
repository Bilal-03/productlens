"""OIDC JWT validation against a configured JWKS endpoint."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError, PyJWKClientError

from app.config import Settings
from app.models.contracts import WorkspaceRole

OIDC_ALLOWED_ALGORITHMS = frozenset({"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"})


class OIDCValidationError(ValueError):
    """Raised when an OIDC assertion cannot be trusted or mapped."""


@dataclass(frozen=True)
class OIDCIdentity:
    subject_id: str
    workspace_id: str
    role: WorkspaceRole
    groups: tuple[str, ...]
    issuer: str


class OIDCValidator:
    """Validate signed OIDC access tokens with cached, rotating JWKS keys.

    ``PyJWKClient`` caches the configured JWKS and refreshes it when a token
    references a new key id. The JWKS URL and issuer are deployment settings,
    never request-controlled values, which prevents the API from becoming an
    arbitrary outbound key-fetch proxy.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        jwks_client: Any | None = None,
        jwks_client_factory: Callable[..., Any] = PyJWKClient,
    ) -> None:
        self.settings = settings
        self.issuer = settings.oidc_issuer_url
        self.audience = settings.oidc_audience
        self.workspace_claim = settings.oidc_workspace_claim
        self.groups_claim = settings.oidc_groups_claim
        self.role_groups = settings.oidc_role_groups
        if jwks_client is not None:
            self.jwks_client = jwks_client
        elif settings.oidc_jwks_url:
            self.jwks_client = jwks_client_factory(
                settings.oidc_jwks_url,
                cache_jwk_set=True,
                lifespan=settings.oidc_jwks_cache_ttl_seconds,
                timeout=settings.oidc_jwks_timeout_seconds,
            )
        else:
            self.jwks_client = None

    def validate(self, token: str) -> OIDCIdentity:
        if (
            not self.issuer
            or not self.audience
            or not self.settings.oidc_jwks_url
            or self.jwks_client is None
        ):
            raise OIDCValidationError("OIDC access is not fully configured")

        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise OIDCValidationError("Malformed OIDC access token") from exc

        algorithm = header.get("alg")
        if algorithm not in OIDC_ALLOWED_ALGORITHMS:
            raise OIDCValidationError("OIDC token uses an unsupported signing algorithm")
        if not isinstance(header.get("kid"), str) or not header["kid"]:
            raise OIDCValidationError("OIDC token is missing a key id")

        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=[algorithm],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
                leeway=0,
            )
        except (InvalidTokenError, PyJWKClientError, TypeError, ValueError) as exc:
            raise OIDCValidationError("OIDC access token validation failed") from exc

        if not isinstance(payload, dict):
            raise OIDCValidationError("OIDC access token claims are invalid")
        subject_id = _required_string_claim(payload, "sub", "subject")
        workspace_id = _required_string_claim(payload, self.workspace_claim, "workspace")
        groups = _groups(payload.get(self.groups_claim))
        role = _role_for_groups(groups, self.role_groups)
        return OIDCIdentity(
            subject_id=subject_id,
            workspace_id=workspace_id,
            role=role,
            groups=groups,
            issuer=self.issuer,
        )


def _required_string_claim(payload: dict[str, Any], claim_name: str, label: str) -> str:
    value = payload.get(claim_name)
    if not isinstance(value, str) or not value or len(value) > 128 or any(ord(char) < 32 for char in value):
        raise OIDCValidationError(f"OIDC token has no valid {label} claim")
    return value


def _groups(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise OIDCValidationError("OIDC token has no valid groups claim")
    unique = dict.fromkeys(
        item for item in value if len(item) <= 128 and not any(ord(char) < 32 for char in item)
    )
    if len(unique) != len(value):
        raise OIDCValidationError("OIDC token has invalid group values")
    return tuple(unique)


def _role_for_groups(groups: tuple[str, ...], role_groups: dict[str, list[str]]) -> WorkspaceRole:
    group_set = set(groups)
    for role in (WorkspaceRole.ADMIN, WorkspaceRole.ANALYST, WorkspaceRole.VIEWER):
        configured_groups = role_groups.get(role.value, [])
        if any(group in group_set for group in configured_groups):
            return role
    raise OIDCValidationError("OIDC groups do not map to a ProductLens role")
