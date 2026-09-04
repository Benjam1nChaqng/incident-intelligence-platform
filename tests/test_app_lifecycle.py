import pytest

import incident_intel.api as api_module
from incident_intel.config import Settings


class DisposableEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


@pytest.mark.anyio
async def test_postgres_app_disposes_owned_engine_on_shutdown(monkeypatch) -> None:
    engine = DisposableEngine()
    monkeypatch.setattr(api_module, "create_engine_from_url", lambda _url: engine)
    app = api_module.create_app(
        settings=Settings(
            storage_backend="postgres",
            database_url="postgresql+psycopg://demo:demo@localhost/demo",
        )
    )

    async with app.router.lifespan_context(app):
        assert engine.disposed is False

    assert engine.disposed is True
