import base64
import ipaddress
import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PQC_KEM_LEVELS = ("ML-KEM-768", "ML-KEM-1024")
PQC_SIGN_LEVELS = ("ML-DSA-65", "ML-DSA-87")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str = "sqlite+pysqlite:///./painscore.db"
    redis_url: str = ""

    master_key: str = ""
    master_key_version: int = 1
    master_key_ring: str = ""
    jwt_secret: str = ""
    jwt_refresh_secret: str = ""

    access_token_ttl_minutes: int = 20
    refresh_token_ttl_days: int = 14

    key_store_path: Path = Path("./keystore")
    model_store_path: Path = Path("./models")
    dataset_path: Path = Path("./datasets")
    epidemic_data_path: Path = Path("./data")
    document_store_path: Path = Path("./storage/documents")
    external_dataset_path: Path = Path("./storage/external")
    signal_store_path: Path = Path("./storage/signals")
    #: Retained camera-and-microphone clips. Its own directory, so a retention rule can be
    #: applied to recordings of patients' faces without touching anything else.
    observation_store_path: Path = Path("./storage/observations")

    pqc_kem_level: str = "ML-KEM-768"
    pqc_sign_level: str = "ML-DSA-65"

    # External dataset synchronisation. Acquisition is capped rather than unlimited:
    # a publisher can change a 2 MB CSV into a 40 GB archive without warning, and an
    # unattended worker should refuse that rather than fill the volume.
    sync_enabled: bool = True
    sync_interval_minutes: int = 360
    sync_auto_acquire: bool = True
    sync_auto_train: bool = True
    sync_max_dataset_bytes: int = 256 * 1024 * 1024
    sync_max_acquisitions_per_run: int = 3
    sync_request_timeout_seconds: int = 60

    # Kaggle's documented API. Dataset search answers anonymously; a download of a dataset
    # whose owner requires a signed-in account does not, and that is the only thing these
    # credentials are used for.
    kaggle_username: str = ""
    kaggle_key: str = ""

    cors_origins: str = "http://localhost:5173,http://localhost:4173"

    trusted_proxies: str = ""
    max_document_bytes: int = 15 * 1024 * 1024
    log_format: str = "text"

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def trusted_proxy_networks(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        networks = []
        for entry in self.trusted_proxies.split(","):
            entry = entry.strip()
            if not entry:
                continue
            networks.append(ipaddress.ip_network(entry, strict=False))
        return networks

    @staticmethod
    def _decode_key(value: str, name: str) -> bytes:
        raw = base64.b64decode(value)
        if len(raw) != 32:
            raise ValueError(f"{name} must decode to exactly 32 bytes")
        return raw

    @property
    def master_key_bytes(self) -> bytes:
        return self._decode_key(self.master_key, "MASTER_KEY")

    @property
    def master_keys(self) -> dict[int, bytes]:
        ring = {self.master_key_version: self.master_key_bytes}
        for entry in self.master_key_ring.split(","):
            entry = entry.strip()
            if not entry:
                continue
            version, _, encoded = entry.partition(":")
            ring.setdefault(
                int(version), self._decode_key(encoded, f"MASTER_KEY_RING[{version}]")
            )
        return ring


@lru_cache
def get_settings() -> Settings:
    settings = Settings()

    for field in ("master_key", "jwt_secret", "jwt_refresh_secret"):
        if not getattr(settings, field):
            if os.getenv("PAINSCORE_ENV") == "production":
                raise RuntimeError(f"{field.upper()} is required in production")
            setattr(settings, field, base64.b64encode(os.urandom(32)).decode())
    if settings.pqc_kem_level not in PQC_KEM_LEVELS:
        raise RuntimeError(f"PQC_KEM_LEVEL must be one of {', '.join(PQC_KEM_LEVELS)}")
    if settings.pqc_sign_level not in PQC_SIGN_LEVELS:
        raise RuntimeError(f"PQC_SIGN_LEVEL must be one of {', '.join(PQC_SIGN_LEVELS)}")
    for directory in (
        settings.key_store_path,
        settings.model_store_path,
        settings.dataset_path,
        settings.epidemic_data_path,
        settings.document_store_path,
        settings.external_dataset_path,
        settings.signal_store_path,
        settings.observation_store_path,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return settings
