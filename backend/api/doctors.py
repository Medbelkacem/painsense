import uuid

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from backend.api import schemas
from database.models import Role, User
from backend.dependencies import AdminUser, DbSession, client_ip
from security import audit
from security import authentication as auth

router = APIRouter(prefix="/api/users", tags=["accounts"])

ROLE_LABELS = {
    Role.SUPER_ADMIN: "Platform administrator",
    Role.CLINIC_ADMIN: "Clinic administrator",
    Role.DOCTOR: "Clinician",
    Role.RESEARCHER: "Researcher",
    Role.AUDITOR: "Auditor",
}


def _may_assign(admin: User, role: Role) -> None:
    if role is Role.SUPER_ADMIN and admin.role is not Role.SUPER_ADMIN:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Only the platform administrator can grant that role",
        )


def _may_manage(admin: User, target: User) -> None:
    if target.role is Role.SUPER_ADMIN and admin.role is not Role.SUPER_ADMIN:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Only the platform administrator can change that account",
        )


@router.get("", response_model=list[schemas.UserOut])
def list_users(db: DbSession, admin: AdminUser) -> list[schemas.UserOut]:
    rows = db.scalars(select(User).order_by(User.display_name))
    return [schemas.UserOut.model_validate(row) for row in rows]


@router.get("/roles", response_model=list[dict])
def roles(admin: AdminUser) -> list[dict]:
    return [{"code": role.value, "label": label} for role, label in ROLE_LABELS.items()]


@router.post("", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: schemas.DoctorCreate, request: Request, db: DbSession, admin: AdminUser
) -> schemas.UserOut:
    _may_assign(admin, payload.role)
    email = payload.email.lower().strip()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="That email is already registered")

    created = User(
        email=email,
        password_hash=auth.hash_password(payload.password),
        display_name=payload.display_name,
        role=payload.role,
        profession=payload.profession,
        clinic_name=payload.clinic_name,
        phone=payload.phone,
        registration_number=payload.registration_number,
        speciality=payload.speciality,
    )
    db.add(created)
    db.commit()
    db.refresh(created)

    audit.record(
        db,
        event_type=audit.SECURITY_EVENT,
        actor_id=admin.id,
        actor_label=admin.email,
        resource="account",
        resource_id=str(created.id),
        client_ip=client_ip(request),
        meta={"action": "account_created", "role": created.role.value, "email": created.email},
    )
    return schemas.UserOut.model_validate(created)


@router.patch("/{user_id}", response_model=schemas.UserOut)
def update_user(
    user_id: uuid.UUID,
    payload: schemas.DoctorUpdate,
    request: Request,
    db: DbSession,
    admin: AdminUser,
) -> schemas.UserOut:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Account not found")
    _may_manage(admin, target)

    changes = payload.model_dump(exclude_unset=True)
    if "role" in changes and changes["role"] is not None:
        _may_assign(admin, changes["role"])
    if target.id == admin.id and changes.get("is_active") is False:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="An administrator cannot disable their own account"
        )
    if target.id == admin.id and "role" in changes and changes["role"] != admin.role:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="An administrator cannot change their own role"
        )
    for field, value in changes.items():
        setattr(target, field, value)
    if changes.get("is_active") is False or "role" in changes:
        auth.revoke_user_sessions(db, target.id)
    db.commit()
    db.refresh(target)

    audit.record(
        db,
        event_type=audit.SECURITY_EVENT,
        actor_id=admin.id,
        actor_label=admin.email,
        resource="account",
        resource_id=str(target.id),
        client_ip=client_ip(request),
        meta={"action": "account_updated", "fields": sorted(changes)},
    )
    return schemas.UserOut.model_validate(target)


@router.post("/{user_id}/unlock", response_model=schemas.UserOut)
def unlock_user(
    user_id: uuid.UUID, request: Request, db: DbSession, admin: AdminUser
) -> schemas.UserOut:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Account not found")
    _may_manage(admin, target)
    auth.unlock_account(db, target)
    audit.record(
        db,
        event_type=audit.SECURITY_EVENT,
        actor_id=admin.id,
        actor_label=admin.email,
        resource="account",
        resource_id=str(target.id),
        client_ip=client_ip(request),
        meta={"action": "account_unlocked"},
    )
    return schemas.UserOut.model_validate(target)


@router.post("/{user_id}/revoke-sessions", response_model=schemas.UserOut)
def revoke_sessions(
    user_id: uuid.UUID, request: Request, db: DbSession, admin: AdminUser
) -> schemas.UserOut:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Account not found")
    _may_manage(admin, target)
    revoked = auth.revoke_user_sessions(db, target.id)
    audit.record(
        db,
        event_type=audit.SECURITY_EVENT,
        actor_id=admin.id,
        actor_label=admin.email,
        resource="account",
        resource_id=str(target.id),
        client_ip=client_ip(request),
        meta={"action": "sessions_revoked", "sessions": revoked},
    )
    return schemas.UserOut.model_validate(target)
