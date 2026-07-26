FROM python:3.11-slim-bookworm@sha256:b18992999dbe963a45a8a4da40ac2b1975be1a776d939d098c647482bcad5cba AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build
COPY backend/requirements.lock /build/requirements.lock
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install --requirement /build/requirements.lock

FROM python:3.11-slim-bookworm@sha256:b18992999dbe963a45a8a4da40ac2b1975be1a776d939d098c647482bcad5cba AS runtime

ARG DAWATRACE_VERSION=0.1.0-alpha.1
ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown

LABEL org.opencontainers.image.title="DawaTrace Backend" \
      org.opencontainers.image.vendor="Esenai Group Ltd" \
      org.opencontainers.image.version="${DAWATRACE_VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_TIME}" \
      com.esenai.dawatrace.fhir.version="4.0.1"

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=dawatrace.settings.production

RUN groupadd --system --gid 10001 dawatrace \
    && useradd --system --uid 10001 --gid dawatrace --home /app dawatrace

COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=dawatrace:dawatrace backend /app

RUN DAWATRACE_SECRET_KEY=build-only-staticfiles-not-a-secret \
    DAWATRACE_OBJECT_SIGNING_KEY=build-only-staticfiles-not-a-secret \
    DAWATRACE_ALLOWED_HOSTS=build.invalid \
    python manage.py collectstatic --noinput

USER dawatrace
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/', timeout=3)"

CMD ["gunicorn", "dawatrace.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-"]
