import hashlib
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pqcrypto.kem import ml_kem_768, ml_kem_1024
from pqcrypto.sign import ml_dsa_65, ml_dsa_87

from config import get_settings

_ED_SIG_LEN = 64
_ED_KEY_LEN = 32
_X25519_KEY_LEN = 32


@dataclass(frozen=True)
class KemLevel:
    name: str
    scheme: str
    module: object


@dataclass(frozen=True)
class SignLevel:
    name: str
    scheme: str
    module: object


KEM_LEVELS = {
    "ML-KEM-768": KemLevel("ML-KEM-768", "X25519+ML-KEM-768", ml_kem_768),
    "ML-KEM-1024": KemLevel("ML-KEM-1024", "X25519+ML-KEM-1024", ml_kem_1024),
}
SIGN_LEVELS = {
    "ML-DSA-65": SignLevel("ML-DSA-65", "Ed25519+ML-DSA-65", ml_dsa_65),
    "ML-DSA-87": SignLevel("ML-DSA-87", "Ed25519+ML-DSA-87", ml_dsa_87),
}
_KEM_BY_SCHEME = {level.scheme: level for level in KEM_LEVELS.values()}
_SIGN_BY_SCHEME = {level.scheme: level for level in SIGN_LEVELS.values()}


def kem_level(name: str | None = None) -> KemLevel:
    return KEM_LEVELS[name or get_settings().pqc_kem_level]


def sign_level(name: str | None = None) -> SignLevel:
    return SIGN_LEVELS[name or get_settings().pqc_sign_level]


def kem_scheme() -> str:
    return kem_level().scheme


def sign_scheme() -> str:
    return sign_level().scheme


def _kem_for_scheme(scheme: str) -> KemLevel:
    try:
        return _KEM_BY_SCHEME[scheme]
    except KeyError as exc:
        raise ValueError(f"unknown key-establishment scheme {scheme}") from exc


def _sign_for_scheme(scheme: str) -> SignLevel:
    try:
        return _SIGN_BY_SCHEME[scheme]
    except KeyError as exc:
        raise ValueError(f"unknown signature scheme {scheme}") from exc


def generate_kem_keypair(scheme: str | None = None) -> tuple[bytes, bytes]:
    level = _kem_for_scheme(scheme) if scheme else kem_level()
    x_sk = x25519.X25519PrivateKey.generate()
    x_pub = x_sk.public_key().public_bytes_raw()
    pq_pub, pq_sk = level.module.keygen()
    return x_pub + bytes(pq_pub), x_sk.private_bytes_raw() + bytes(pq_sk)


def encapsulate_key(public_key: bytes, scheme: str | None = None) -> tuple[bytes, bytes]:
    level = _kem_for_scheme(scheme) if scheme else kem_level()
    x_peer = x25519.X25519PublicKey.from_public_bytes(public_key[:_X25519_KEY_LEN])
    ephemeral = x25519.X25519PrivateKey.generate()
    classical = ephemeral.exchange(x_peer)

    pq_ct, pq_secret = level.module.encaps(public_key[_X25519_KEY_LEN:])
    ciphertext = ephemeral.public_key().public_bytes_raw() + bytes(pq_ct)
    return ciphertext, _combine(classical, bytes(pq_secret), ciphertext, level.scheme)


def decapsulate_key(secret_key: bytes, ciphertext: bytes, scheme: str | None = None) -> bytes:
    level = _kem_for_scheme(scheme) if scheme else kem_level()
    x_sk = x25519.X25519PrivateKey.from_private_bytes(secret_key[:_X25519_KEY_LEN])
    peer = x25519.X25519PublicKey.from_public_bytes(ciphertext[:_X25519_KEY_LEN])
    classical = x_sk.exchange(peer)

    pq_secret = level.module.decaps(secret_key[_X25519_KEY_LEN:], ciphertext[_X25519_KEY_LEN:])
    return _combine(classical, bytes(pq_secret), ciphertext, level.scheme)


def _combine(classical: bytes, pq: bytes, transcript: bytes, scheme: str) -> bytes:
    kdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"painsense/kem/v2/" + scheme.encode(),
    )
    return kdf.derive(classical + pq + hashlib.sha256(transcript).digest())


def generate_signature_keypair(scheme: str | None = None) -> tuple[bytes, bytes]:
    level = _sign_for_scheme(scheme) if scheme else sign_level()
    ed_sk = ed25519.Ed25519PrivateKey.generate()
    pq_pub, pq_sk = level.module.keygen()
    return ed_sk.public_key().public_bytes_raw() + bytes(pq_pub), (
        ed_sk.private_bytes_raw() + bytes(pq_sk)
    )


def sign_data(secret_key: bytes, message: bytes, scheme: str | None = None) -> bytes:
    level = _sign_for_scheme(scheme) if scheme else sign_level()
    ed_sk = ed25519.Ed25519PrivateKey.from_private_bytes(secret_key[:_ED_KEY_LEN])
    ed_sig = ed_sk.sign(message)
    pq_sig = level.module.sign(secret_key[_ED_KEY_LEN:], message)
    return ed_sig + bytes(pq_sig)


def verify_signature(
    public_key: bytes, message: bytes, signature: bytes, scheme: str | None = None
) -> bool:
    try:
        level = _sign_for_scheme(scheme) if scheme else sign_level()
        ed_pub = ed25519.Ed25519PublicKey.from_public_bytes(public_key[:_ED_KEY_LEN])
        ed_pub.verify(signature[:_ED_SIG_LEN], message)
        level.module.verify(public_key[_ED_KEY_LEN:], message, signature[_ED_SIG_LEN:])
    except (InvalidSignature, ValueError):
        return False
    return True


def fingerprint(public_key: bytes) -> str:
    return hashlib.sha256(public_key).hexdigest()[:32]
