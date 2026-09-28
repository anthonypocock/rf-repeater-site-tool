FROM python:3.12-slim AS rf-core-build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates git make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY native/rf-core native/rf-core
COPY data/sample-region data/sample-region
RUN ./native/rf-core/scripts/fetch_ntia_itm.sh \
    && make -C native/rf-core build \
    && make -C native/rf-core test


FROM python:3.12-slim

ENV MVP_HOST=0.0.0.0 \
    MVP_PORT=8080 \
    MVP_AUTH_ENABLED=false \
    MVP_SUPABASE_URL= \
    MVP_SUPABASE_PUBLISHABLE_KEY= \
    MVP_RESULTS_ROOT=/app/.cache/rf-results \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app

WORKDIR /app
COPY --chown=app:app apps/web apps/web
COPY --chown=app:app services services
COPY --chown=app:app --from=rf-core-build /app/native/rf-core/bin native/rf-core/bin
RUN mkdir -p /app/.cache/rf-data /app/.cache/rf-results && chown -R app:app /app/.cache

USER app
EXPOSE 8080
VOLUME ["/app/.cache/rf-data", "/app/.cache/rf-results"]

CMD ["python3", "services/api/mvp_server.py"]
