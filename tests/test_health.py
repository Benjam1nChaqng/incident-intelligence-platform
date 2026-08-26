import httpx
import pytest

from incident_intel.api import app


@pytest.mark.anyio
async def test_health_endpoint_returns_service_metadata() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "service": "incident-intelligence-platform",
        "status": "ok",
        "version": "0.1.0",
    }
