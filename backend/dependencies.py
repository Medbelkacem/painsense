import ipaddress
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Iterator
from threading import Lock
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from config import get_settings
from database.session import SessionLocal
from database.models import ADMIN_ROLES, CLINICAL_ROLES, Role, User
from security import authentication as auth


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _trusted_proxy(address: str | None) -> bool:
    if not address:
        return False
    try:
        candidate = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(candidate in network for network in get_settings().trusted_proxy_networks)


def client_ip(request: Request) -> str | None:
    peer = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and _trusted_proxy(peer):
        return forwarded.split(",")[0].strip() or peer
    return peer


class RateLimiter:
    SWEEP_INTERVAL = 60.0

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()
        self._swept_at = time.monotonic()

    def _sweep(self, now: float, window_seconds: int) -> None:
        if now - self._swept_at < self.SWEEP_INTERVAL:
            return
        self._swept_at = now
        stale = [
            key
            for key, hits in self._hits.items()
            if not hits or hits[-1] <= now - window_seconds
        ]
        for key in stale:
            del self._hits[key]

    def retry_after(self, key: str, limit: int, window_seconds: int) -> int:
        now = time.monotonic()
        with self._lock:
            self._sweep(now, window_seconds)
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


class RedisRateLimiter:
    def __init__(self, url: str) -> None:
        import redis

        self._redis = redis.Redis.from_url(url, socket_timeout=1.0)

    @staticmethod
    def _key(key: str) -> str:
        return f"painsense:rate:{key}"

    def retry_after(self, key: str, limit: int, window_seconds: int) -> int:
        name = self._key(key)
        now = time.time()
        self._redis.zremrangebyscore(name, 0, now - window_seconds)
        if self._redis.zcard(name) < limit:
            return 0
        oldest = self._redis.zrange(name, 0, 0, withscores=True)
        first = oldest[0][1] if oldest else now
        return int(window_seconds - (now - first)) + 1

    def record(self, key: str) -> None:
        name = self._key(key)
        now = time.time()
        pipe = self._redis.pipeline()
        pipe.zadd(name, {f"{now:.6f}-{uuid.uuid4().hex[:8]}": now})
        pipe.expire(name, 3600)
        pipe.execute()

    def check(self, key: str, limit: int, window_seconds: int) -> int:
        wait = self.retry_after(key, limit, window_seconds)
        if wait == 0:
            self.record(key)
        return wait

    def reset(self) -> None:
        for name in self._redis.scan_iter("painsense:rate:*"):
            self._redis.delete(name)


def _build_limiter():
    url = get_settings().redis_url
    return RedisRateLimiter(url) if url else RateLimiter()


limiter = _build_limiter()


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
        subject = uuid.UUID(str(claims.get("sub", "")))
    except (auth.AuthError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = db.get(User, subject)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Account unavailable")
    if auth.token_issued_before_revocation(user, claims):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Session has been signed out")
    request.state.user = user
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_roles(*roles: Role, message: str):
    allowed = frozenset(roles)

    def dependency(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=message)
        return user

    return dependency


require_admin = require_roles(
    *ADMIN_ROLES, message="This action is restricted to administrators"
)
require_super_admin = require_roles(
    Role.SUPER_ADMIN, message="This action is restricted to the platform administrator"
)
require_clinical = require_roles(
    *CLINICAL_ROLES, message="Patient records are available to clinical accounts only"
)
require_research = require_roles(
    *ADMIN_ROLES,
    Role.RESEARCHER,
    message="The research tools are available to research and administrator accounts",
)
require_audit = require_roles(
    *ADMIN_ROLES,
    Role.AUDITOR,
    message="The audit trail and security posture are available to auditors and administrators",
)

AdminUser = Annotated[User, Depends(require_admin)]
SuperAdminUser = Annotated[User, Depends(require_super_admin)]
ClinicalUser = Annotated[User, Depends(require_clinical)]
ResearchUser = Annotated[User, Depends(require_research)]
AuditUser = Annotated[User, Depends(require_audit)]
