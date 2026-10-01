import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

GENESIS_HASH = "0" * 64
SESSION_INFO = b"painscore-session-key"

PERMISSIONS = {
    "patient": {"give_consent", "read_own_estimate"},
    "nurse": {"read_own_estimate", "read_estimates", "read_quality", "change_scenario"},
    "doctor": {
        "read_own_estimate",
        "read_estimates",
        "read_quality",
        "change_scenario",
        "read_raw_signals",
        "export_record",
        "read_audit",
    },
    "admin": {"read_audit", "verify_audit", "manage_keys", "read_quality"},
}

COMPLIANCE = {
    "consent": "A session refuses to start until consent is recorded for the pseudonymised subject.",
    "minimisation": "Only the derived window features are processed; no name, no address, no raw video or audio is persisted.",
    "pseudonymisation": "Subjects are identified as VP-nn; the register that would resolve them is outside this prototype.",
    "integrity": "Every access is hash-chained and signed, so a removed or edited entry breaks verification.",
    "purpose": "Research prototype for pain estimation. Not a medical device and not a diagnosis.",
}


class PermissionDenied(Exception):
    pass


class ConsentMissing(Exception):
    pass


class LiboqsProvider:
    name = "liboqs-python"
    kem = "ML-KEM-768"
    signature = "ML-DSA-65"
    post_quantum = True
    warning = ""

    def __init__(self, module):
        self.oqs = module

    def kem_keypair(self):
        client = self.oqs.KeyEncapsulation(self.kem)
        return client.generate_keypair(), client

    def encapsulate(self, public_key):
        with self.oqs.KeyEncapsulation(self.kem) as peer:
            ciphertext, shared = peer.encap_secret(public_key)
        return shared, ciphertext

    def decapsulate(self, secret, ciphertext):
        return secret.decap_secret(ciphertext)

    def signing_keypair(self):
        signer = self.oqs.Signature(self.signature)
        return signer.generate_keypair(), signer

    def sign(self, secret, message):
        return secret.sign(message)

    def verify(self, public_key, message, signature):
        with self.oqs.Signature(self.signature) as verifier:
            return bool(verifier.verify(message, signature, public_key))


class LatticeProvider:
    name = "kyber-py + dilithium-py"
    kem = "ML-KEM-768"
    signature = "ML-DSA-65"
    post_quantum = True
    warning = ""

    def __init__(self, ml_kem, ml_dsa):
        self.ml_kem = ml_kem
        self.ml_dsa = ml_dsa

    def kem_keypair(self):
        public_key, secret_key = self.ml_kem.keygen()
        return public_key, secret_key

    def encapsulate(self, public_key):
        shared, ciphertext = self.ml_kem.encaps(public_key)
        return shared, ciphertext

    def decapsulate(self, secret, ciphertext):
        return self.ml_kem.decaps(secret, ciphertext)

    def signing_keypair(self):
        public_key, secret_key = self.ml_dsa.keygen()
        return public_key, secret_key

    def sign(self, secret, message):
        return self.ml_dsa.sign(secret, message)

    def verify(self, public_key, message, signature):
        return bool(self.ml_dsa.verify(public_key, message, signature))


class ClassicalProvider:
    name = "classical fallback"
    kem = "X25519"
    signature = "Ed25519"
    post_quantum = False
    warning = (
        "No post-quantum library available. Key exchange is X25519 and signatures are Ed25519, "
        "so the records are NOT protected against a quantum adversary."
    )

    def kem_keypair(self):
        secret = X25519PrivateKey.generate()
        return (
            secret.public_key().public_bytes(
                encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
            ),
            secret,
        )

    def encapsulate(self, public_key):
        ephemeral = X25519PrivateKey.generate()
        shared = ephemeral.exchange(X25519PublicKey.from_public_bytes(public_key))
        return shared, ephemeral.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )

    def decapsulate(self, secret, ciphertext):
        return secret.exchange(X25519PublicKey.from_public_bytes(ciphertext))

    def signing_keypair(self):
        secret = Ed25519PrivateKey.generate()
        return (
            secret.public_key().public_bytes(
                encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
            ),
            secret,
        )

    def sign(self, secret, message):
        return secret.sign(message)

    def verify(self, public_key, message, signature):
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
        except Exception:
            return False
        return True


def select_provider():
    try:
        import oqs

        if "ML-KEM-768" in oqs.get_enabled_kem_mechanisms():
            return LiboqsProvider(oqs)
    except Exception:
        pass
    try:
        from dilithium_py.ml_dsa import ML_DSA_65
        from kyber_py.ml_kem import ML_KEM_768

        return LatticeProvider(ML_KEM_768, ML_DSA_65)
    except Exception:
        pass
    return ClassicalProvider()


PROVIDER = select_provider()


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def permitted(role, permission):
    return permission in PERMISSIONS.get(role, set())


def require(role, permission):
    if not permitted(role, permission):
        raise PermissionDenied(f"role {role} may not {permission}")


@dataclass
class AuditEntry:
    index: int
    recorded_at: str
    role: str
    action: str
    subject: str
    payload_hash: str
    previous_hash: str
    entry_hash: str
    signature: str


class AuditLog:
    def __init__(self, provider=PROVIDER):
        self.provider = provider
        self.verifying_key, self.signing_key = provider.signing_keypair()
        self.chain = []

    def _body(self, index, recorded_at, role, action, subject, payload_hash, previous_hash):
        return canonical(
            {
                "index": index,
                "recorded_at": recorded_at,
                "role": role,
                "action": action,
                "subject": subject,
                "payload_hash": payload_hash,
                "previous_hash": previous_hash,
            }
        )

    def append(self, role, action, subject="", payload=None):
        index = len(self.chain)
        previous_hash = self.chain[-1].entry_hash if self.chain else GENESIS_HASH
        payload_hash = digest(canonical(payload)) if payload is not None else GENESIS_HASH
        recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        body = self._body(index, recorded_at, role, action, subject, payload_hash, previous_hash)
        entry_hash = digest(body)
        signature = self.provider.sign(self.signing_key, entry_hash.encode())
        entry = AuditEntry(
            index=index,
            recorded_at=recorded_at,
            role=role,
            action=action,
            subject=subject,
            payload_hash=payload_hash,
            previous_hash=previous_hash,
            entry_hash=entry_hash,
            signature=signature.hex(),
        )
        self.chain.append(entry)
        return entry

    def verify(self):
        previous_hash = GENESIS_HASH
        for entry in self.chain:
            if entry.previous_hash != previous_hash:
                return False, f"entry {entry.index} does not follow entry {entry.index - 1}"
            body = self._body(
                entry.index,
                entry.recorded_at,
                entry.role,
                entry.action,
                entry.subject,
                entry.payload_hash,
                entry.previous_hash,
            )
            if digest(body) != entry.entry_hash:
                return False, f"entry {entry.index} has been edited"
            if not self.provider.verify(self.verifying_key, entry.entry_hash.encode(), bytes.fromhex(entry.signature)):
                return False, f"entry {entry.index} has an invalid signature"
            previous_hash = entry.entry_hash
        return True, f"{len(self.chain)} entries verified"

    def records(self, limit=None):
        chain = self.chain if limit is None else self.chain[-limit:]
        return [asdict(entry) for entry in chain]


@dataclass
class ConsentRegistry:
    granted: dict = field(default_factory=dict)

    def grant(self, subject, scope="pain estimation research prototype"):
        self.granted[subject] = {
            "scope": scope,
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        return self.granted[subject]

    def revoke(self, subject):
        self.granted.pop(subject, None)

    def holds(self, subject):
        return subject in self.granted

    def require(self, subject):
        if not self.holds(subject):
            raise ConsentMissing(f"no consent recorded for {subject}")


class Vault:
    def __init__(self, provider=PROVIDER):
        self.provider = provider
        self.public_key, self.secret_key = provider.kem_keypair()
        self.session_key = None
        self.encapsulation = None

    def open_session(self):
        shared, ciphertext = self.provider.encapsulate(self.public_key)
        self.encapsulation = ciphertext
        self.session_key = HKDF(
            algorithm=hashes.SHA256(), length=32, salt=None, info=SESSION_INFO
        ).derive(shared)
        return {
            "kem": self.provider.kem,
            "cipher": "AES-256-GCM",
            "signature": self.provider.signature,
            "encapsulation_bytes": len(ciphertext),
            "post_quantum": self.provider.post_quantum,
        }

    def confirm_session(self):
        shared = self.provider.decapsulate(self.secret_key, self.encapsulation)
        derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=SESSION_INFO).derive(shared)
        return derived == self.session_key

    def seal(self, record, subject=""):
        if self.session_key is None:
            self.open_session()
        nonce = os.urandom(12)
        plaintext = canonical(record)
        ciphertext = AESGCM(self.session_key).encrypt(nonce, plaintext, subject.encode())
        return {"nonce": nonce.hex(), "ciphertext": ciphertext.hex(), "subject": subject}

    def unseal(self, envelope):
        plaintext = AESGCM(self.session_key).decrypt(
            bytes.fromhex(envelope["nonce"]),
            bytes.fromhex(envelope["ciphertext"]),
            envelope["subject"].encode(),
        )
        return json.loads(plaintext)


class SecureSession:
    def __init__(self, provider=PROVIDER):
        self.provider = provider
        self.vault = Vault(provider)
        self.audit = AuditLog(provider)
        self.consent = ConsentRegistry()
        self.handshake = self.vault.open_session()

    def start(self, subject, role="nurse"):
        require(role, "read_estimates")
        self.consent.require(subject)
        self.audit.append(role, "session.start", subject)

    def record_estimate(self, role, subject, estimate):
        require(role, "read_estimates")
        self.consent.require(subject)
        envelope = self.vault.seal(estimate, subject)
        self.audit.append(role, "estimate.store", subject, payload=estimate)
        return envelope

    def status(self):
        verified, message = self.audit.verify()
        return {
            "provider": self.provider.name,
            "kem": self.provider.kem,
            "cipher": "AES-256-GCM",
            "signature": self.provider.signature,
            "post_quantum": self.provider.post_quantum,
            "warning": self.provider.warning,
            "handshake": self.handshake,
            "audit_entries": len(self.audit.chain),
            "audit_verified": verified,
            "audit_message": message,
            "consented_subjects": sorted(self.consent.granted),
            "roles": {role: sorted(rights) for role, rights in PERMISSIONS.items()},
            "compliance": COMPLIANCE,
        }


def self_check():
    session = SecureSession()
    print(f"provider            {PROVIDER.name} ({PROVIDER.kem} / {PROVIDER.signature})")
    if PROVIDER.warning:
        print(f"warning             {PROVIDER.warning}")
    print(f"shared secret agree {session.vault.confirm_session()}")

    session.consent.grant("VP-07")
    session.start("VP-07", "nurse")
    envelope = session.record_estimate("nurse", "VP-07", {"estimated_pain": 6.4, "confidence": 81.2})
    print(f"sealed record       {len(envelope['ciphertext']) // 2} bytes of ciphertext")
    print(f"unsealed record     {session.vault.unseal(envelope)}")

    try:
        session.record_estimate("admin", "VP-07", {"estimated_pain": 6.4})
    except PermissionDenied as denial:
        print(f"rbac denial         {denial}")
    try:
        session.start("VP-99", "doctor")
    except ConsentMissing as missing:
        print(f"consent gate        {missing}")

    print(f"audit verify        {session.audit.verify()}")
    session.audit.chain[1].action = "estimate.delete"
    print(f"after tampering     {session.audit.verify()}")


if __name__ == "__main__":
    self_check()
