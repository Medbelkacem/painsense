"""Verification of the ledger and of the audit hash chain.

Verification is deliberately pessimistic: it recomputes every hash from the stored fields
rather than trusting the stored hash, and it checks the signature on every block. A report
names the first height that fails and what failed, because "the chain is broken somewhere"
is not actionable.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.blockchain import ledger
from app.blockchain.hashing import ZERO_HASH, canonical, digest
from app.database.models import AuditLog, LedgerBlock
from app.security import key_management, pqc


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


def verify_chain(db: Session) -> ChainReport:
    blocks = db.scalars(select(LedgerBlock).order_by(LedgerBlock.height)).all()
    signing_key = key_management.ledger_signing_key()
    report = ChainReport(
        valid=True,
        blocks_checked=len(blocks),
        signature_scheme=signing_key.scheme,
        key_fingerprint=signing_key.fingerprint,
    )

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

        body = ledger.stored_payload(block)
        recomputed = digest(body)
        if recomputed != block.block_hash:
            report.problems.append(
                Problem(
                    block.height,
                    "HASH_MISMATCH",
                    "block contents do not hash to the stored block hash",
                )
            )
        elif not pqc.verify_signature(signing_key.public, canonical(body), block.signature):
            report.problems.append(
                Problem(
                    block.height,
                    "BAD_SIGNATURE",
                    "signature does not verify against the ledger key",
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
    """The fields covered by an audit entry's hash.

    Kept here next to the verifier so the writer and the checker cannot drift apart.
    """
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
