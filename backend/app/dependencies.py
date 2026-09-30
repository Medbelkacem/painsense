"""Shared request dependencies: sessions, the current user, roles and rate limits."""

import time
import uuid
from collections import defaultdict, deque
from collections.abc import Iterator
from threading import Lock
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database.database import SessionLocal
from app.database.models import Role, User
from app.security import authentication as auth


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


class RateLimiter:
    """Fixed-window counter, per key, held in this process.

    Enough for one application process, which is how the prototype runs. A deployment
    behind several workers needs a shared store; nothing outside this class changes when
    that is swapped in.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def retry_after(self, key: str, limit: int, window_seconds: int) -> int:
        """Zero when the call is allowed, otherwise seconds to wait. Records nothing."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - window_seconds:
                hits.popleft()
            return int(window_seconds - (now - hits[0])) + 1 if len(hits) >= limit else 0

    def record(self, key: str) -> None:
        with self._lock:
            self._hits[key].append(time.monotonic())

    def check(self, key: str, limit: int, window_seconds: int) -> int:
        wait = self.retry_after(key, limit, window_seconds)
        if wait == 0:
            self.record(key)
        return wait

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def rate_limit(name: str, limit: int, window_seconds: int = 60):
    def dependency(request: Request) -> None:
        key = f"{name}:{client_ip(request) or 'unknown'}"
        retry_after = limiter.check(key, limit, window_seconds)
        if retry_after:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Try again shortly.",
                headers={"Retry-After": str(retry_after)},
            )

    return dependency


DbSession = Annotated[Session, Depends(get_db)]


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


def current_user(request: Request, db: DbSession) -> User:
    try:
        claims = auth.decode_access_token(_bearer(request))
    except auth.AuthError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = db.get(User, uuid.UUID(claims["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Account unavailable")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_admin(user: CurrentUser) -> User:
    if user.role is not Role.ADMIN:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="This action is restricted to administrators"
        )
    return user


AdminUser = Annotated[User, Depends(require_admin)]
