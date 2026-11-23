# Solstice web app container. Built in Azure with `az acr build` (see infra/README.md).
# Layout mirrors the repo so config.py finds config/ and data/ two levels above backend/solstice/.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend/solstice backend/solstice
COPY config config
COPY data/raw data/raw
COPY data/policies data/policies

# Run as a non-root user; only data/runtime (tickets, traces, audit) is writable.
RUN useradd --create-home --uid 10001 app \
 && mkdir -p data/runtime && chown -R app:app data/runtime
USER app

EXPOSE 8000
# --proxy-headers: trust the Container Apps ingress so the real client address is used (PIN lockout).
CMD ["python", "-m", "uvicorn", "solstice.web.app:app", "--app-dir", "/app/backend", \
     "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
