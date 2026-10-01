from datetime import datetime, timezone

from sqlalchemy import select

from database.models import AuditLog, LedgerBlock
from security import audit, ledger

RECORD = {"code": "PS-2026-000421", "estimated_pain": 7.2, "locations": ["CHEST_CENTRAL"]}


def test_hash_ignores_key_order():
    assert ledger.digest({"a": 1, "b": 2}) == ledger.digest({"b": 2, "a": 1})


def test_hash_changes_with_the_smallest_edit():
    assert ledger.digest(RECORD) != ledger.digest({**RECORD, "estimated_pain": 7.3})


def test_equivalent_instants_hash_the_same():
    utc = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
    naive = datetime(2026, 9, 30, 12, 0)
    assert ledger.digest({"at": utc}) == ledger.digest({"at": naive})


def append(db, count=3):
    return [
        ledger.append_block(
            db,
            event_type="ASSESSMENT_CREATED",
            resource="assessment",
            record_id=f"record-{index}",
            payload={**RECORD, "index": index},
        )
        for index in range(count)
    ]


def test_the_chain_starts_at_the_zero_hash(db):
    genesis = db.scalar(select(LedgerBlock).where(LedgerBlock.height == 0))
    assert genesis is not None
    assert genesis.previous_hash == ledger.ZERO_HASH


def test_each_block_links_to_the_one_before(db):
    start = ledger.height(db)
    blocks = append(db)
    assert [block.height for block in blocks] == [start, start + 1, start + 2]
    assert blocks[1].previous_hash == blocks[0].block_hash
    assert blocks[2].previous_hash == blocks[1].block_hash


def test_a_clean_chain_verifies(db):
    start = ledger.height(db)
    append(db)
    report = ledger.verify_chain(db)
    assert report.valid
    assert report.blocks_checked == start + 3
    assert report.problems == []


def test_editing_a_record_hash_is_detected(db):
    target = append(db)[1]
    target.record_hash = ledger.ZERO_HASH
    db.commit()

    report = ledger.verify_chain(db)
    assert not report.valid
    assert report.problems[0].height == target.height
    assert report.problems[0].kind == "HASH_MISMATCH"


def test_removing_a_block_breaks_the_chain(db):
    db.delete(append(db)[1])
    db.commit()

    report = ledger.verify_chain(db)
    assert not report.valid
    assert {problem.kind for problem in report.problems} >= {"HEIGHT_GAP", "BROKEN_LINK"}


def test_a_forged_signature_is_detected(db):
    blocks = append(db, 1)
    block = blocks[0]

    block.signature = bytes(len(block.signature))
    db.commit()

    report = ledger.verify_chain(db)
    assert not report.valid
    assert report.problems[0].kind == "BAD_SIGNATURE"


def test_the_ledger_holds_no_clinical_content(db):
    block = append(db, 1)[0]
    stored = " ".join(str(value) for value in ledger.stored_payload(block).values())
    assert "PS-2026-000421" not in stored
    assert "CHEST_CENTRAL" not in stored
    assert "7.2" not in stored


def test_audit_entries_are_numbered_and_chained(db):
    added = [
        audit.record(db, event_type=audit.LOGIN, resource="session", resource_id=str(index))
        for index in range(3)
    ]

    assert [entry.seq for entry in added] == [added[0].seq, added[0].seq + 1, added[0].seq + 2]
    assert added[1].previous_hash == added[0].entry_hash
    assert added[2].previous_hash == added[1].entry_hash
    assert ledger.verify_audit_chain(db).valid


def test_the_audit_chain_starts_at_the_zero_hash(db):
    first = db.scalar(select(AuditLog).order_by(AuditLog.seq))
    assert first.seq == 1
    assert first.previous_hash == ledger.ZERO_HASH


def test_editing_an_audit_entry_is_detected(db):
    entry = audit.record(db, event_type=audit.LOGIN, resource="session", resource_id="1")
    audit.record(db, event_type=audit.PATIENT_CREATED, resource="patient", resource_id="2")

    entry.event_type = audit.LOGOUT
    db.commit()

    report = ledger.verify_audit_chain(db)
    assert not report.valid
    assert report.problems[0].kind == "HASH_MISMATCH"


def test_a_ledgered_event_writes_a_block(db):
    before = ledger.height(db)
    audit.record(
        db,
        event_type=audit.PATIENT_CREATED,
        resource="patient",
        resource_id="PS-2026-000001",
        ledger_payload=RECORD,
    )
    assert ledger.height(db) == before + 1


def test_a_plain_event_writes_no_block(db):
    before = ledger.height(db)
    audit.record(db, event_type=audit.LOGIN, resource="session", resource_id="1")
    assert ledger.height(db) == before
