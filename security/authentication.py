import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import get_settings
from database.models import SessionToken, User

LOCKOUT_THRESHOLD = 5
LOCKOUT_MINUTES = 15

_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)


class AuthError(Exception):
    pass


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored: str, candidate: str) -> bool:
    try:
        _hasher.verify(stored, candidate)
    except VerificationError:
        return False
    return True


def needs_rehash(stored: str) -> bool:
    return _hasher.check_needs_rehash(stored)


TOKEN_ISSUER = "painsense"
TOKEN_AUDIENCE = "painsense-api"


def issue_access_token(user: User) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "iss": TOKEN_ISSUER,
        "aud": TOKEN_AUDIENCE,
        "sub": str(user.id),
        "role": user.role.value,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=["HS256"],
            audience=TOKEN_AUDIENCE,
            issuer=TOKEN_ISSUER,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthError("invalid or expired token") from exc


def token_issued_before_revocation(user: User, claims: dict) -> bool:
    if user.sessions_revoked_at is None:
        return False
    issued = datetime.fromtimestamp(int(claims["iat"]), tz=timezone.utc)
    return issued < user.sessions_revoked_at


def _refresh_digest(raw: str) -> str:
    secret = get_settings().jwt_refresh_secret.encode()
    return hmac.new(secret, raw.encode(), hashlib.sha256).hexdigest()


def issue_refresh_token(
    db: Session, user: User, user_agent: str | None = None, client_ip: str | None = None
) -> str:
    settings = get_settings()
    raw = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    db.add(
        SessionToken(
            user_id=user.id,
            token_hash=_refresh_digest(raw),
            expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
            user_agent=(user_agent or "")[:255] or None,
            client_ip=client_ip,
            last_used_at=now,
        )
    )
    db.commit()
    return raw


def consume_refresh_token(db: Session, raw: str) -> User:
    row = db.scalar(select(SessionToken).where(SessionToken.token_hash == _refresh_digest(raw)))
    if row is None or row.revoked:
        raise AuthError("refresh token not recognised")
    if row.expires_at < datetime.now(timezone.utc):
        raise AuthError("refresh token expired")

    row.revoked = True
    db.commit()
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise AuthError("account unavailable")
    return user


def revoke_refresh_token(db: Session, raw: str) -> bool:
    row = db.scalar(select(SessionToken).where(SessionToken.token_hash == _refresh_digest(raw)))
    if row is None or row.revoked:
        return False
    row.revoked = True
    db.commit()
    return True


def revoke_user_sessions(db: Session, user_id: uuid.UUID) -> int:
    rows = db.scalars(
        select(SessionToken).where(
            SessionToken.user_id == user_id, SessionToken.revoked.is_(False)
        )
    ).all()
    for row in rows:
        row.revoked = True
    user = db.get(User, user_id)
    if user is not None:
        user.sessions_revoked_at = datetime.now(timezone.utc)
    db.commit()
    return len(rows)


def active_sessions(db: Session, user_id: uuid.UUID) -> list[SessionToken]:
    now = datetime.now(timezone.utc)
    return list(
        db.scalars(
            select(SessionToken)
            .where(
                SessionToken.user_id == user_id,
                SessionToken.revoked.is_(False),
                SessionToken.expires_at > now,
            )
            .order_by(SessionToken.issued_at.desc())
        )
    )


def prune_sessions(db: Session) -> int:
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(SessionToken).where(
            (SessionToken.revoked.is_(True)) | (SessionToken.expires_at < now)
        )
    ).all()
    for row in rows:
        db.delete(row)
    db.commit()
    return len(rows)


def unlock_account(db: Session, user: User) -> None:
    user.failed_attempts = 0
    user.locked_until = None
    db.commit()


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email.lower().strip()))
    if user is None:
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
