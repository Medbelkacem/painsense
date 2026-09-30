"""Hybrid classical + post-quantum primitives.

Both halves must hold for the construction to break, so adopting ML-KEM/ML-DSA never
weakens what X25519 and Ed25519 already give us. This mirrors the transition guidance
around FIPS 203/204 rather than swapping the classical primitives out.

Nothing here implements a cipher: ML-KEM-768 and ML-DSA-65 come from pqcrypto (PQClean
builds), X25519 and Ed25519 from the cryptography package.
"""

import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pqcrypto.kem import ml_kem_768 as mlkem
from pqcrypto.sign import ml_dsa_65 as mldsa

KEM_SCHEME = "X25519+ML-KEM-768"
SIGN_SCHEME = "Ed25519+ML-DSA-65"

_ED_SIG_LEN = 64
_ED_KEY_LEN = 32
# X25519 public and private keys are both 32 bytes, so one constant covers both slices.
_X25519_KEY_LEN = 32


def generate_kem_keypair() -> tuple[bytes, bytes]:
    x_sk = x25519.X25519PrivateKey.generate()
    x_pub = x_sk.public_key().public_bytes_raw()
    pq_pub, pq_sk = mlkem.keygen()
    return x_pub + bytes(pq_pub), x_sk.private_bytes_raw() + bytes(pq_sk)


def encapsulate_key(public_key: bytes) -> tuple[bytes, bytes]:
    x_peer = x25519.X25519PublicKey.from_public_bytes(public_key[:_X25519_KEY_LEN])
    ephemeral = x25519.X25519PrivateKey.generate()
    classical = ephemeral.exchange(x_peer)

    pq_ct, pq_secret = mlkem.encaps(public_key[_X25519_KEY_LEN:])
    ciphertext = ephemeral.public_key().public_bytes_raw() + bytes(pq_ct)
    return ciphertext, _combine(classical, bytes(pq_secret), ciphertext)


def decapsulate_key(secret_key: bytes, ciphertext: bytes) -> bytes:
    x_sk = x25519.X25519PrivateKey.from_private_bytes(secret_key[:_X25519_KEY_LEN])
    peer = x25519.X25519PublicKey.from_public_bytes(ciphertext[:_X25519_KEY_LEN])
    classical = x_sk.exchange(peer)

    pq_secret = mlkem.decaps(secret_key[_X25519_KEY_LEN:], ciphertext[_X25519_KEY_LEN:])
    return _combine(classical, bytes(pq_secret), ciphertext)


def _combine(classical: bytes, pq: bytes, transcript: bytes) -> bytes:
    # Concatenating both secrets before the KDF is what makes the result at least as
    # strong as the stronger half; the transcript is bound in so the shared secret is
    # tied to this exact exchange.
    kdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"painscore/kem/v1")
    return kdf.derive(classical + pq + hashlib.sha256(transcript).digest())


def generate_signature_keypair() -> tuple[bytes, bytes]:
    ed_sk = ed25519.Ed25519PrivateKey.generate()
    pq_pub, pq_sk = mldsa.keygen()
    return ed_sk.public_key().public_bytes_raw() + bytes(pq_pub), (
        ed_sk.private_bytes_raw() + bytes(pq_sk)
    )


def sign_data(secret_key: bytes, message: bytes) -> bytes:
    ed_sk = ed25519.Ed25519PrivateKey.from_private_bytes(secret_key[:_ED_KEY_LEN])
    ed_sig = ed_sk.sign(message)
    pq_sig = mldsa.sign(secret_key[_ED_KEY_LEN:], message)
    return ed_sig + bytes(pq_sig)


def verify_signature(public_key: bytes, message: bytes, signature: bytes) -> bool:
    try:
        ed_pub = ed25519.Ed25519PublicKey.from_public_bytes(public_key[:_ED_KEY_LEN])
        ed_pub.verify(signature[:_ED_SIG_LEN], message)
        mldsa.verify(public_key[_ED_KEY_LEN:], message, signature[_ED_SIG_LEN:])
    except (InvalidSignature, ValueError):
        # ValueError covers pqcrypto's InvalidSignatureError as well as a key or
        # signature of the wrong length.
        return False
    return True


def fingerprint(public_key: bytes) -> str:
    return hashlib.sha256(public_key).hexdigest()[:32]
