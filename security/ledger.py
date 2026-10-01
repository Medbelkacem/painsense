import hashlib
import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.models import AuditLog, LedgerBlock
from database.session import serialise_appends
from security import key_management, pqc

ZERO_HASH = "0" * 64


def _plain(value):
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def canonical(payload: dict) -> bytes:
    return json.dumps(
        _plain(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest(payload: dict) -> str:
    return hashlib.sha256(canonical(payload)).hexdigest()


def digest_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


_append_lock = threading.Lock()


def _block_payload(
    height: int,
    timestamp: datetime,
    event_type: str,
    resource: str,
    record_id: str,
    record_hash: str,
    actor_id: str | None,
    previous_hash: str,
) -> dict:
    return {
        "height": height,
        "timestamp": timestamp,
        "event_type": event_type,
        "resource": resource,
        "record_id": record_id,
        "record_hash": record_hash,
        "actor_id": actor_id,
        "previous_hash": previous_hash,
    }


def head(db: Session) -> LedgerBlock | None:
    return db.scalar(select(LedgerBlock).order_by(LedgerBlock.height.desc()).limit(1))


def height(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(LedgerBlock)) or 0


def append_block(
    db: Session,
    *,
    event_type: str,
    resource: str,
    record_id: str,
    payload: dict,
    actor_id: uuid.UUID | str | None = None,
    commit: bool = True,
) -> LedgerBlock:
    record_hash = digest(payload)
    signing_key = key_management.ledger_signing_key()

    with _append_lock:
        serialise_appends(db, "ledger")
        previous = head(db)
        next_height = 0 if previous is None else previous.height + 1
        previous_hash = ZERO_HASH if previous is None else previous.block_hash
        timestamp = datetime.now(timezone.utc)
        actor = str(actor_id) if actor_id else None

        body = _block_payload(
            next_height,
            timestamp,
            event_type,
            resource,
            record_id,
            record_hash,
            actor,
            previous_hash,
        )
        block_hash = digest(body)
        block = LedgerBlock(
            height=next_height,
            timestamp=timestamp,
            event_type=event_type,
            resource=resource,
            record_id=record_id,
            record_hash=record_hash,
            actor_id=actor,
            previous_hash=previous_hash,
            block_hash=block_hash,
            signature=pqc.sign_data(signing_key.secret, canonical(body), signing_key.scheme),
            signature_scheme=signing_key.scheme,
            key_id=signing_key.key_id,
        )
        db.add(block)
        if commit:
            db.commit()
        else:
            db.flush()
    return block


def stored_payload(block: LedgerBlock) -> dict:
    return _block_payload(
        block.height,
        block.timestamp,
        block.event_type,
        block.resource,
        block.record_id,
        block.record_hash,
        block.actor_id,
        block.previous_hash,
    )


@dataclass
class Problem:
    height: int
    kind: str
    detail: str


@dataclass
class ChainReport:
    valid: bool
    blocks_checked: int
    signature_scheme: str | None
    key_fingerprint: str | None
    problems: list[Problem] = field(default_factory=list)


def _key_for(block: LedgerBlock, cache: dict) -> key_management.KeyPair | None:
    key_id = block.key_id or f"{key_management.LEDGER_SIGNING}-v1"
    if key_id not in cache:
        try:
            version = int(key_id.rsplit("-v", 1)[1])
            cache[key_id] = key_management.ledger_signing_key_version(version)
        except (KeyError, ValueError, FileNotFoundError):
            cache[key_id] = None
    return cache[key_id]


def verify_chain(db: Session) -> ChainReport:
    blocks = db.scalars(select(LedgerBlock).order_by(LedgerBlock.height)).all()
    signing_key = key_management.ledger_signing_key()
    report = ChainReport(
        valid=True,
        blocks_checked=len(blocks),
        signature_scheme=signing_key.scheme,
        key_fingerprint=signing_key.fingerprint,
    )
    keys: dict[str, key_management.KeyPair | None] = {}

    expected_previous = ZERO_HASH
    for index, block in enumerate(blocks):
        if block.height != index:
            report.problems.append(
                Problem(block.height, "HEIGHT_GAP", f"expected height {index}")
            )
        if block.previous_hash != expected_previous:
            report.problems.append(
                Problem(
                    block.height,
                    "BROKEN_LINK",
                    "previous hash does not match the block before it",
                )
            )

        body = stored_payload(block)
        recomputed = digest(body)
        if recomputed != block.block_hash:
            report.problems.append(
                Problem(
                    block.height,
                    "HASH_MISMATCH",
                    "block contents do not hash to the stored block hash",
                )
            )
        else:
            key = _key_for(block, keys)
            if key is None:
                report.problems.append(
                    Problem(
                        block.height,
                        "KEY_MISSING",
                        f"the keystore holds no {block.key_id} to verify against",
                    )
                )
            elif not pqc.verify_signature(
                key.public, canonical(body), block.signature, block.signature_scheme
            ):
                report.problems.append(
                    Problem(
                        block.height,
                        "BAD_SIGNATURE",
                        f"signature does not verify against {key.key_id}",
                    )
                )

        expected_previous = block.block_hash

    report.valid = not report.problems
    return report


@dataclass
class AuditReport:
    valid: bool
    entries_checked: int
    problems: list[Problem] = field(default_factory=list)


def verify_audit_chain(db: Session) -> AuditReport:
    entries = db.scalars(select(AuditLog).order_by(AuditLog.seq)).all()
    report = AuditReport(valid=True, entries_checked=len(entries))

    expected_previous = ZERO_HASH
    for index, entry in enumerate(entries, start=1):
        if entry.seq != index:
            report.problems.append(
                Problem(entry.seq, "SEQUENCE_GAP", f"expected sequence {index}")
            )
        if entry.previous_hash != expected_previous:
            report.problems.append(
                Problem(
                    entry.seq, "BROKEN_LINK", "previous hash does not match the entry before it"
                )
            )
        if digest(audit_payload(entry)) != entry.entry_hash:
            report.problems.append(
                Problem(
                    entry.seq,
                    "HASH_MISMATCH",
                    "entry contents do not hash to the stored entry hash",
                )
            )
        expected_previous = entry.entry_hash

    report.valid = not report.problems
    return report


def audit_payload(entry: AuditLog) -> dict:
    return {
        "seq": entry.seq,
        "timestamp": entry.timestamp,
        "actor_id": entry.actor_id,
        "actor_label": entry.actor_label,
        "event_type": entry.event_type,
        "resource": entry.resource,
        "resource_id": entry.resource_id,
        "client_ip": entry.client_ip,
        "meta": entry.meta,
        "previous_hash": entry.previous_hash,
    }
