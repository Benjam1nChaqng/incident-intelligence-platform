FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY pyproject.toml README.md ./
COPY migrations ./migrations
COPY alembic.ini ./
COPY src ./src

RUN python -m pip install --no-cache-dir .

USER app
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"

CMD ["python", "-m", "uvicorn", "incident_intel.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
