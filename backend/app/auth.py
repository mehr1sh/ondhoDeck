"""Supabase Auth token verification and the current-user dependency.

The browser sends `Authorization: Bearer <supabase access token>`. The token is verified here,
on the server, on every request:

* asymmetric tokens (ES256/RS256, Supabase JWT signing keys) against the project's JWKS;
* legacy HS256 tokens against SUPABASE_JWT_SECRET (also used by a local Supabase Auth server).

Audience, expiry and (when SUPABASE_URL is set) issuer are enforced. The user id is taken only
from the verified `sub` claim - never from request bodies or query parameters.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import get_db
from .errors import ApiError
from .models import Profile

log = logging.getLogger("slipslopes.auth")
ASYMMETRIC_ALGS = ("ES256", "RS256", "EdDSA")


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str | None
    role: str


@lru_cache
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=600, timeout=5)


def verify_token(token: str, settings: Settings) -> dict:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise ApiError(401, "invalid_token", "Malformed access token.") from exc
    alg = header.get("alg")
    options = {"require": ["exp", "sub", "aud"]}
    kwargs: dict = {"audience": settings.supabase_jwt_audience, "options": options, "leeway": 10}
    if settings.jwt_issuer:
        kwargs["issuer"] = settings.jwt_issuer
    try:
        if alg == "HS256":
            if not settings.supabase_jwt_secret:
                raise ApiError(401, "invalid_token", "HS256 tokens are not accepted by this deployment.")
            return jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], **kwargs)
        if alg in ASYMMETRIC_ALGS:
            if not settings.jwks_url:
                raise ApiError(401, "invalid_token", "Asymmetric tokens require SUPABASE_URL to be configured.")
            key = _jwks_client(settings.jwks_url).get_signing_key_from_jwt(token)
            return jwt.decode(token, key.key, algorithms=[alg], **kwargs)
    except jwt.ExpiredSignatureError as exc:
        raise ApiError(401, "token_expired", "Your session has expired. Please sign in again.") from exc
    except jwt.PyJWKClientError as exc:
        log.warning("JWKS lookup failed: %s", type(exc).__name__)
        raise ApiError(401, "invalid_token", "Could not verify the access token signature.") from exc
    except jwt.PyJWTError as exc:
        raise ApiError(401, "invalid_token", "Invalid access token.") from exc
    raise ApiError(401, "invalid_token", "Unsupported token algorithm.")


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(401, "not_authenticated", "Sign in to continue.")
    return token.strip()


def get_current_user(request: Request, db: Session = Depends(get_db),
                     settings: Settings = Depends(get_settings)) -> CurrentUser:
    claims = verify_token(_bearer(request), settings)
    if claims.get("role") not in (None, "authenticated"):
        raise ApiError(403, "forbidden", "This token cannot be used to access user data.")
    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except ValueError as exc:
        raise ApiError(401, "invalid_token", "Invalid subject in access token.") from exc
    email = claims.get("email")
    # Lazily create the profile linked to the auth identity.
    profile = db.scalar(select(Profile).where(Profile.id == user_id))
    if profile is None:
        db.add(Profile(id=user_id, email=email))
        db.commit()
    elif email and profile.email != email:
        profile.email = email
        db.commit()
    request.state.user_id = str(user_id)
    return CurrentUser(id=user_id, email=email, role="authenticated")
