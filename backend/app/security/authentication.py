import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.models import SessionToken, User

LOCKOUT_THRESHOLD = 5
LOCKOUT_MINUTES = 15

# Pinned rather than left to the library defaults, so a change of those defaults cannot
# silently weaken logins. Only parallelism differs from them: two lanes instead of four.
_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)


class AuthError(Exception):
    pass


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored: str, candidate: str) -> bool:
    # InvalidHashError is left to propagate: a malformed hash is corrupted data, not a
    # wrong password, and swallowing it would lock the account out with no trace of why.
    try:
        _hasher.verify(stored, candidate)
    except VerificationError:
        return False
    return True


def needs_rehash(stored: str) -> bool:
    return _hasher.check_needs_rehash(stored)


def issue_access_token(user: User) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise AuthError("invalid or expired token") from exc


def issue_refresh_token(db: Session, user: User, user_agent: str | None = None) -> str:
    settings = get_settings()
    raw = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_ttl_days)
    db.add(
        SessionToken(
            user_id=user.id,
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            expires_at=expires_at,
            user_agent=(user_agent or "")[:255] or None,
        )
    )
    db.commit()
    return raw


def consume_refresh_token(db: Session, raw: str) -> User:
    digest = hashlib.sha256(raw.encode()).hexdigest()
    row = db.scalar(select(SessionToken).where(SessionToken.token_hash == digest))
    if row is None or row.revoked:
        raise AuthError("refresh token not recognised")
    if row.expires_at < datetime.now(timezone.utc):
        raise AuthError("refresh token expired")

    # One use per token: a replay of the old value after rotation must fail.
    row.revoked = True
    db.commit()
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise AuthError("account unavailable")
    return user


def revoke_user_sessions(db: Session, user_id: uuid.UUID) -> int:
    rows = db.scalars(
        select(SessionToken).where(
            SessionToken.user_id == user_id, SessionToken.revoked.is_(False)
        )
    ).all()
    for row in rows:
        row.revoked = True
    db.commit()
    return len(rows)


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email.lower().strip()))
    if user is None:
        # Spend comparable time on a missing account so timing does not leak existence.
        _hasher.hash(password)
        raise AuthError("invalid credentials")

    now = datetime.now(timezone.utc)
    if user.locked_until and user.locked_until > now:
        raise AuthError("account temporarily locked")

    if not verify_password(user.password_hash, password):
        user.failed_attempts += 1
        if user.failed_attempts >= LOCKOUT_THRESHOLD:
            user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            user.failed_attempts = 0
        db.commit()
        raise AuthError("invalid credentials")

    if not user.is_active:
        raise AuthError("account disabled")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.failed_attempts = 0
    user.locked_until = None
    db.commit()
    return user
