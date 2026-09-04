import pytest
from fastapi import FastAPI

from incident_intel.api import create_app
from incident_intel.ingestion import InMemoryIngestionStore


@pytest.fixture
def app() -> FastAPI:
    return create_app(ingestion_store=InMemoryIngestionStore())
