"""Supabase JWT auth — module-level deps for FastAPI (monkeypatchable in tests)."""
from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Header, HTTPException

from backend import config


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None


class AuthError(Exception):
    pass


def verify_token(token: str) -> CurrentUser:
    secret = config.SUPABASE_JWT_SECRET
    if not secret:
        raise AuthError("JWT secret not configured")
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as exc:
        raise AuthError(str(exc)) from exc
    sub = claims.get("sub")
    if not sub:
        raise AuthError("missing sub claim")
    return CurrentUser(id=sub, email=claims.get("email"))


def _parse_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def require_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    token = _parse_bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="missing or invalid authorization")
    try:
        return verify_token(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def optional_user(authorization: str | None = Header(default=None)) -> CurrentUser | None:
    token = _parse_bearer(authorization)
    if not token:
        return None
    try:
        return verify_token(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
