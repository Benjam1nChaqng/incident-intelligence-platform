import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

StorageBackend = Literal["memory", "postgres"]


@dataclass(frozen=True)
class Settings:
    storage_backend: StorageBackend
    database_url: str | None = None

    def __post_init__(self) -> None:
        if self.storage_backend not in {"memory", "postgres"}:
            raise ValueError("INCIDENT_INTEL_STORAGE_BACKEND must be memory or postgres")
        if self.storage_backend == "postgres" and not self.database_url:
            raise ValueError("INCIDENT_INTEL_DATABASE_URL is required for postgres storage")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        source = os.environ if environ is None else environ
        backend = source.get("INCIDENT_INTEL_STORAGE_BACKEND", "").strip().lower()

        if not backend:
            raise ValueError("INCIDENT_INTEL_STORAGE_BACKEND is required")
        if backend not in {"memory", "postgres"}:
            raise ValueError("INCIDENT_INTEL_STORAGE_BACKEND must be memory or postgres")

        database_url = source.get("INCIDENT_INTEL_DATABASE_URL", "").strip() or None
        if backend == "postgres" and database_url is None:
            raise ValueError("INCIDENT_INTEL_DATABASE_URL is required for postgres storage")

        return cls(
            storage_backend=cast(StorageBackend, backend),
            database_url=database_url if backend == "postgres" else None,
        )
