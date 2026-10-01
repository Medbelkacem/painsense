from datetime import datetime, timedelta, timezone

import jwt
import pytest

from config import get_settings
from database.models import Role, User
from security import authentication as auth

EMAIL = "n.haddad@chu-batna.dz"
PASSWORD = "T4rget-Rotation-Sept"


def make_doctor(db, password=PASSWORD):
    user = User(
        email=EMAIL,
        password_hash=auth.hash_password(password),
        display_name="Dr N. Haddad",
        role=Role.DOCTOR,
    )
    db.add(user)
    db.commit()
    return user


def test_authenticate_accepts_the_right_password(db):
    user = make_doctor(db)
    assert auth.authenticate(db, EMAIL, PASSWORD).id == user.id


def test_email_is_matched_case_insensitively(db):
    make_doctor(db)
    assert auth.authenticate(db, "  N.Haddad@CHU-Batna.dz  ", PASSWORD)


def test_unknown_email_is_rejected(db):
    with pytest.raises(auth.AuthError):
        auth.authenticate(db, "inconnu@chu-batna.dz", PASSWORD)


def test_wrong_password_counts_towards_the_lockout(db):
    user = make_doctor(db)
    with pytest.raises(auth.AuthError):
        auth.authenticate(db, EMAIL, "mauvais mot de passe")
    assert user.failed_attempts == 1


def test_account_locks_after_repeated_failures(db):
    user = make_doctor(db)
    for _ in range(auth.LOCKOUT_THRESHOLD):
        with pytest.raises(auth.AuthError):
            auth.authenticate(db, EMAIL, "mauvais mot de passe")
    assert user.locked_until is not None
    with pytest.raises(auth.AuthError, match="locked"):
        auth.authenticate(db, EMAIL, PASSWORD)


def test_successful_login_clears_the_failure_count(db):
    user = make_doctor(db)
    with pytest.raises(auth.AuthError):
        auth.authenticate(db, EMAIL, "mauvais mot de passe")
    auth.authenticate(db, EMAIL, PASSWORD)
    assert user.failed_attempts == 0
    assert user.locked_until is None


def test_disabled_account_is_refused(db):
    user = make_doctor(db)
    user.is_active = False
    db.commit()
    with pytest.raises(auth.AuthError):
        auth.authenticate(db, EMAIL, PASSWORD)


def test_password_hash_does_not_contain_the_password(db):
    user = make_doctor(db)
    assert PASSWORD not in user.password_hash
    assert user.password_hash.startswith("$argon2id$")


def test_access_token_carries_the_subject_and_role(db):
    user = make_doctor(db)
    claims = auth.decode_access_token(auth.issue_access_token(user))
    assert claims["sub"] == str(user.id)
    assert claims["role"] == Role.DOCTOR.value


def test_token_signed_with_another_secret_is_rejected(db):
    user = make_doctor(db)
    forged = jwt.encode({"sub": str(user.id), "role": Role.DOCTOR.value}, "n'importe quoi")
    with pytest.raises(auth.AuthError):
        auth.decode_access_token(forged)


def test_expired_access_token_is_rejected(db):
    user = make_doctor(db)
    expired = jwt.encode(
        {"sub": str(user.id), "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
        get_settings().jwt_secret,
    )
    with pytest.raises(auth.AuthError):
        auth.decode_access_token(expired)


def test_refresh_token_works_exactly_once(db):
    user = make_doctor(db)
    raw = auth.issue_refresh_token(db, user)
    assert auth.consume_refresh_token(db, raw).id == user.id
    with pytest.raises(auth.AuthError):
        auth.consume_refresh_token(db, raw)


def test_refresh_token_is_not_stored_in_clear(db):
    user = make_doctor(db)
    raw = auth.issue_refresh_token(db, user)
    stored = db.query(auth.SessionToken).one()
    assert stored.token_hash != raw
    assert len(stored.token_hash) == 64


def test_revoking_sessions_invalidates_outstanding_tokens(db):
    user = make_doctor(db)
    raw = auth.issue_refresh_token(db, user)
    assert auth.revoke_user_sessions(db, user.id) == 1
    with pytest.raises(auth.AuthError):
        auth.consume_refresh_token(db, raw)
