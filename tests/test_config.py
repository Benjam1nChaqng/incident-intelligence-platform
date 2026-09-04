import pytest

from incident_intel.config import Settings


def test_settings_accept_explicit_memory_backend() -> None:
    settings = Settings.from_env({"INCIDENT_INTEL_STORAGE_BACKEND": "memory"})

    assert settings.storage_backend == "memory"
    assert settings.database_url is None


def test_settings_accept_postgres_backend_with_database_url() -> None:
    settings = Settings.from_env(
        {
            "INCIDENT_INTEL_STORAGE_BACKEND": "postgres",
            "INCIDENT_INTEL_DATABASE_URL": "postgresql+psycopg://demo:demo@localhost/demo",
        }
    )

    assert settings.storage_backend == "postgres"
    assert settings.database_url == "postgresql+psycopg://demo:demo@localhost/demo"


def test_settings_reject_missing_backend() -> None:
    with pytest.raises(ValueError, match="INCIDENT_INTEL_STORAGE_BACKEND"):
        Settings.from_env({})


def test_settings_reject_postgres_without_database_url() -> None:
    with pytest.raises(ValueError, match="INCIDENT_INTEL_DATABASE_URL"):
        Settings.from_env({"INCIDENT_INTEL_STORAGE_BACKEND": "postgres"})


def test_settings_reject_unknown_backend_without_echoing_value() -> None:
    unknown_value = "unsupported-secret-like-value"

    with pytest.raises(ValueError) as error:
        Settings.from_env({"INCIDENT_INTEL_STORAGE_BACKEND": unknown_value})

    assert "INCIDENT_INTEL_STORAGE_BACKEND" in str(error.value)
    assert unknown_value not in str(error.value)
