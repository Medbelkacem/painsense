import json

from security import key_management, pqc


def test_hybrid_kem_agrees_on_a_shared_secret():
    public, secret = pqc.generate_kem_keypair()
    ciphertext, sender_secret = pqc.encapsulate_key(public)
    assert pqc.decapsulate_key(secret, ciphertext) == sender_secret


def test_two_encapsulations_give_different_secrets():
    public, secret = pqc.generate_kem_keypair()
    first, _ = pqc.encapsulate_key(public)
    second, _ = pqc.encapsulate_key(public)
    assert pqc.decapsulate_key(secret, first) != pqc.decapsulate_key(secret, second)


def test_signature_round_trip():
    public, secret = pqc.generate_signature_keypair()
    assert pqc.verify_signature(public, b"block 1", pqc.sign_data(secret, b"block 1"))


def test_altered_message_fails_verification():
    public, secret = pqc.generate_signature_keypair()
    assert not pqc.verify_signature(public, b"block 2", pqc.sign_data(secret, b"block 1"))


ED25519_SIG_LEN = 64


def test_post_quantum_half_of_the_signature_is_checked():
    public, secret = pqc.generate_signature_keypair()
    valid = pqc.sign_data(secret, b"block 1")
    other = pqc.sign_data(secret, b"block 2")
    spliced = valid[:ED25519_SIG_LEN] + other[ED25519_SIG_LEN:]
    assert not pqc.verify_signature(public, b"block 1", spliced)


def test_classical_half_of_the_signature_is_checked():
    public, secret = pqc.generate_signature_keypair()
    valid = pqc.sign_data(secret, b"block 1")
    other = pqc.sign_data(secret, b"block 2")
    spliced = other[:ED25519_SIG_LEN] + valid[ED25519_SIG_LEN:]
    assert not pqc.verify_signature(public, b"block 1", spliced)


def test_truncated_signature_fails_verification():
    public, secret = pqc.generate_signature_keypair()
    signature = pqc.sign_data(secret, b"block 1")
    assert not pqc.verify_signature(public, b"block 1", signature[:-8])


def test_keystore_reuses_its_material_across_calls():
    first, second = key_management.ledger_signing_key(), key_management.ledger_signing_key()
    assert first.public == second.public
    assert first.fingerprint == second.fingerprint


def test_keystore_migrates_legacy_metadata_without_replacing_keys(tmp_path):
    public, secret = pqc.generate_signature_keypair("Ed25519+ML-DSA-65")
    (tmp_path / "ledger-signing.pub").write_bytes(public)
    (tmp_path / "ledger-signing.key").write_bytes(secret)
    (tmp_path / "ledger-signing.json").write_text(
        json.dumps({"scheme": "Ed25519+ML-DSA-65", "fingerprint": pqc.fingerprint(public)})
    )

    migrated = key_management.Keystore(tmp_path).current("ledger-signing")

    assert migrated.public == public
    assert migrated.secret == secret
    assert migrated.scheme == "Ed25519+ML-DSA-65"


def test_signing_and_transport_keys_are_distinct():
    signing = key_management.ledger_signing_key()
    transport = key_management.transport_kem_key()
    assert signing.public != transport.public
    assert signing.scheme != transport.scheme


def test_secret_key_files_are_not_readable_by_others():
    key_management.ledger_signing_key()
    key_management.transport_kem_key()

    secrets = sorted(key_management.keystore_path().glob("*.key"))
    assert secrets, "no secret key was written to the keystore"
    for path in secrets:
        assert path.stat().st_mode & 0o077 == 0, path.name
