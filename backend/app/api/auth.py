"""Sign in, token rotation and sign out.

The access token is short-lived and travels in the Authorization header. The refresh token
is long-lived, so it is kept in an HttpOnly cookie where page scripts cannot read it. That
choice brings cross-site request forgery into scope for the two endpoints that act on the
cookie, so both require a double-submit CSRF token: a value the client reads from a readable
cookie and echoes in a header. An attacker's page can cause the browser to send the cookie
but cannot read it to build the matching header.
"""

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select

from app.api import schemas
from app.config import get_settings
from app.database.models import Role, User
from app.dependencies import CurrentUser, DbSession, client_ip, limiter, rate_limit
from app.security import audit
from app.security import authentication as auth

router = APIRouter(prefix="/api/auth", tags=["authentication"])

# Only failed sign-ins count towards the limit. A hospital network presents one address
# for a whole department, so throttling successful logins would lock out everyone behind
# it; throttling failures still blunts credential spraying, and an individual account is
# separately protected by the lockout counter.
FAILED_LOGIN_LIMIT = 10
FAILED_LOGIN_WINDOW_SECONDS = 300

# Registration is open, so it is throttled on every call rather than only on failures.
REGISTRATION_LIMIT = 5
REGISTRATION_WINDOW_SECONDS = 3600

REFRESH_COOKIE = "painscore_refresh"
CSRF_COOKIE = "painscore_csrf"
CSRF_HEADER = "X-CSRF-Token"


def _secure_cookies(request: Request) -> bool:
    return request.url.scheme == "https"


def _issue(response: Response, request: Request, db, user) -> schemas.TokenResponse:
    settings = get_settings()
    refresh = auth.issue_refresh_token(db, user, request.headers.get("user-agent"))
    csrf = secrets.token_urlsafe(32)
    secure = _secure_cookies(request)

    response.set_cookie(
        REFRESH_COOKIE,
        refresh,
        max_age=settings.refresh_token_ttl_days * 86400,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/api/auth",
    )
    # Deliberately readable by the client: this is the half it has to echo back in a header.
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=settings.refresh_token_ttl_days * 86400,
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/",
    )
    return schemas.TokenResponse(
        access_token=auth.issue_access_token(user),
        expires_in=settings.access_token_ttl_minutes * 60,
        csrf_token=csrf,
        user=schemas.UserOut.model_validate(user),
    )


def _require_csrf(request: Request) -> None:
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="CSRF token missing or mismatched"
        )


@router.post("/login", response_model=schemas.TokenResponse)
def login(
    payload: schemas.LoginRequest, request: Request, response: Response, db: DbSession
) -> schemas.TokenResponse:
    failures_key = f"login-failures:{client_ip(request) or 'unknown'}"
    wait = limiter.retry_after(failures_key, FAILED_LOGIN_LIMIT, FAILED_LOGIN_WINDOW_SECONDS)
    if wait:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed sign-in attempts. Try again shortly.",
            headers={"Retry-After": str(wait)},
        )

    try:
        user = auth.authenticate(db, payload.email, payload.password)
    except auth.AuthError as exc:
        limiter.record(failures_key)
        audit.record(
            db,
            event_type=audit.LOGIN_FAILED,
            actor_label=payload.email,
            resource="session",
            client_ip=client_ip(request),
            meta={"reason": str(exc)},
        )
        # The same status and wording for a wrong password and an unknown account, so the
        # response does not tell an attacker which addresses exist.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials") from exc

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    audit.record(
        db,
        event_type=audit.LOGIN,
        actor_id=user.id,
        actor_label=user.email,
        resource="session",
        resource_id=str(user.id),
        client_ip=client_ip(request),
    )
    return _issue(response, request, db, user)


@router.post(
    "/refresh",
    response_model=schemas.TokenResponse,
    dependencies=[Depends(rate_limit("refresh", limit=60, window_seconds=300))],
)
def refresh(request: Request, response: Response, db: DbSession) -> schemas.TokenResponse:
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        # No cookie means no session to protect, and the client asking on start-up should be
        # told there is nothing to restore rather than that its CSRF token was wrong.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="No refresh token presented")
    _require_csrf(request)
    try:
        user = auth.consume_refresh_token(db, raw)
    except auth.AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    audit.record(
        db,
        event_type=audit.TOKEN_REFRESH,
        actor_id=user.id,
        actor_label=user.email,
        resource="session",
        resource_id=str(user.id),
        client_ip=client_ip(request),
    )
    return _issue(response, request, db, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: DbSession, user: CurrentUser) -> None:
    _require_csrf(request)
    revoked = auth.revoke_user_sessions(db, user.id)
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
    response.delete_cookie(CSRF_COOKIE, path="/")
    audit.record(
        db,
        event_type=audit.LOGOUT,
        actor_id=user.id,
        actor_label=user.email,
        resource="session",
        resource_id=str(user.id),
        client_ip=client_ip(request),
        meta={"sessions_revoked": revoked},
    )


@router.get("/me", response_model=schemas.UserOut)
def me(user: CurrentUser) -> schemas.UserOut:
    return schemas.UserOut.model_validate(user)


@router.post(
    "/register",
    response_model=schemas.TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(rate_limit("register", REGISTRATION_LIMIT, REGISTRATION_WINDOW_SECONDS))
    ],
)
def register(
    payload: schemas.RegistrationRequest, request: Request, response: Response, db: DbSession
) -> schemas.TokenResponse:
    """Create a clinician account and sign the person in.

    The role is fixed here rather than taken from the request: an open form must not be a
    way to obtain administrator rights.
    """
    email = payload.email.lower().strip()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="An account already exists for that email address"
        )

    user = User(
        email=email,
        password_hash=auth.hash_password(payload.password),
        display_name=payload.display_name.strip(),
        clinic_name=payload.clinic_name.strip(),
        phone=payload.phone.strip(),
        profession=payload.profession,
        speciality=(payload.speciality or "").strip() or None,
        registration_number=(payload.registration_number or "").strip() or None,
        role=Role.DOCTOR,
        last_login_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    audit.record(
        db,
        event_type=audit.ACCOUNT_REGISTERED,
        actor_id=user.id,
        actor_label=user.email,
        resource="account",
        resource_id=str(user.id),
        client_ip=client_ip(request),
        meta={"profession": user.profession.value, "clinic": user.clinic_name},
    )
    return _issue(response, request, db, user)
