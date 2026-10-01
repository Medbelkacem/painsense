import pytest
from cryptography.exceptions import InvalidTag

from security import encryption

IDENTITY = {"code": "PS-2026-000421", "given_name": "Amel", "family_name": "Cherif"}


def test_record_round_trip():
    ciphertext, wrapped = encryption.encrypt_record(IDENTITY)
    assert encryption.decrypt_record(ciphertext, wrapped) == IDENTITY


def test_plaintext_does_not_survive_in_the_ciphertext():
    ciphertext, _ = encryption.encrypt_record(IDENTITY)
    assert b"Cherif" not in ciphertext


def test_each_record_gets_its_own_data_key():
    first, first_key = encryption.encrypt_record(IDENTITY)
    second, second_key = encryption.encrypt_record(IDENTITY)
    assert first != second
    assert first_key != second_key


def test_associated_data_is_authenticated():
    ciphertext, wrapped = encryption.encrypt_record(IDENTITY, aad=b"patient:PS-2026-000421")
    with pytest.raises(InvalidTag):
        encryption.decrypt_record(ciphertext, wrapped, aad=b"patient:PS-2026-000999")


def test_tampered_ciphertext_is_rejected():
    ciphertext, wrapped = encryption.encrypt_record(IDENTITY)
    flipped = bytearray(ciphertext)
    flipped[-1] ^= 0xFF
    with pytest.raises(InvalidTag):
        encryption.decrypt_record(bytes(flipped), wrapped)


def test_wrapped_key_from_another_record_does_not_open_it():
    ciphertext, _ = encryption.encrypt_record(IDENTITY)
    _, other_key = encryption.encrypt_record(IDENTITY)
    with pytest.raises(InvalidTag):
        encryption.decrypt_record(ciphertext, other_key)
