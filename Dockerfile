FROM python:3.14.7-slim-trixie@sha256:caaf356f40667c496d405780745b9ac25771c189a51dfcc42430d531ea09f8a2

LABEL org.opencontainers.image.title="Premier League Prediction Platform"
LABEL org.opencontainers.image.description="Read-only FastAPI backend runtime"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLP_ENVIRONMENT=production \
    PLP_ARTIFACT_ROOT=/runtime/artifacts \
    PLP_REGISTRY_ROOT=/runtime/artifacts/registry

WORKDIR /app

RUN groupadd --system --gid 10001 plp \
    && useradd --system --uid 10001 --gid 10001 --home-dir /nonexistent \
        --shell /usr/sbin/nologin plp \
    && mkdir --parents /runtime/artifacts \
    && chown --recursive 10001:10001 /runtime

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir .

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2).read()"]

ENTRYPOINT ["python", "-m", "pl_platform.api.production_runtime"]
