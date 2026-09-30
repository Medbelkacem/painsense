"""Append-only ledger of record hashes.

What the ledger holds is a hash, a link to the previous block and a signature. No clinical
content: no names, no findings, no measurements, no document bytes. Deriving the patient
from a block is not merely forbidden by policy, there is nothing in the row to derive it
from.

The signature is what separates this from a plain hash chain. Rewriting history means
producing a valid signature for every rewritten block, and the signing key is kept in the
file-backed keystore outside the database.
"""

import threading
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.blockchain.hashing import ZERO_HASH, canonical, digest
from app.database.models import LedgerBlock
from app.security import key_management, pqc

# Heights have to be handed out in the same order as the hash links. A single in-process
# lock is enough for one application process, which is how the prototype is deployed; a
# multi-process deployment needs a database-level lock in its place.
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
) -> LedgerBlock:
    """Hash the record, chain it to the current head and sign the block."""
    record_hash = digest(payload)
    signing_key = key_management.ledger_signing_key()

    with _append_lock:
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
            signature=pqc.sign_data(signing_key.secret, canonical(body)),
            signature_scheme=signing_key.scheme,
        )
        db.add(block)
        db.commit()
    return block


def stored_payload(block: LedgerBlock) -> dict:
    """The exact body that was hashed and signed when the block was written."""
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
