"""Account administration."""

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api import schemas
from app.database.models import User
from app.dependencies import AdminUser, CurrentUser, DbSession, client_ip
from app.security import audit
from app.security import authentication as auth

router = APIRouter(prefix="/api/doctors", tags=["accounts"])


@router.get("", response_model=list[schemas.UserOut])
def list_doctors(db: DbSession, user: CurrentUser) -> list[schemas.UserOut]:
    rows = db.scalars(select(User).order_by(User.display_name))
    return [schemas.UserOut.model_validate(row) for row in rows]


@router.post("", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def create_doctor(
    payload: schemas.DoctorCreate, request: Request, db: DbSession, admin: AdminUser
) -> schemas.UserOut:
    email = payload.email.lower().strip()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="That email is already registered")

    created = User(
        email=email,
        password_hash=auth.hash_password(payload.password),
        display_name=payload.display_name,
        role=payload.role,
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
def update_doctor(
    user_id: uuid.UUID,
    payload: schemas.DoctorUpdate,
    request: Request,
    db: DbSession,
    admin: AdminUser,
) -> schemas.UserOut:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Account not found")

    changes = payload.model_dump(exclude_unset=True)
    if target.id == admin.id and changes.get("is_active") is False:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="An administrator cannot disable their own account"
        )
    for field, value in changes.items():
        setattr(target, field, value)
    if changes.get("is_active") is False:
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
