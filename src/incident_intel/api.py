from fastapi import FastAPI
from pydantic import BaseModel

from incident_intel import __version__


class HealthResponse(BaseModel):
    service: str
    status: str
    version: str


app = FastAPI(
    title="Incident Intelligence Platform",
    version=__version__,
    summary="Synthetic support incident investigation API.",
)


@app.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    return HealthResponse(
        service="incident-intelligence-platform",
        status="ok",
        version=__version__,
    )
