import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


@pytest.fixture(scope="session")
def database_url() -> str:
    value = os.environ.get("INCIDENT_INTEL_TEST_DATABASE_URL")
    if not value:
        pytest.skip("INCIDENT_INTEL_TEST_DATABASE_URL is required for integration tests")
    return value


@pytest.fixture(scope="session")
def database_engine(database_url: str) -> Engine:
    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    yield engine
    engine.dispose()
