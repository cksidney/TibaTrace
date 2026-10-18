FROM python:3.11-alpine@sha256:d9368b3a5ac59afea7b5d4f2e2aea0941dbf9fdee9c369c5bec00b98244bc929 AS base

# Keep the minimal runtime and its packaging tools on reviewed security fixes.
RUN apk add --no-cache --upgrade zlib=1.3.2-r1 \
    && python -m pip install --no-cache-dir --upgrade pip==26.2.1 setuptools==83.0.0 wheel==0.46.3

FROM base AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build
COPY backend/requirements.lock /build/requirements.lock
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip==26.2.1 setuptools==83.0.0 wheel==0.46.3 \
    && /opt/venv/bin/pip install --requirement /build/requirements.lock

FROM base AS runtime

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

RUN addgroup -S -g 10001 dawatrace \
    && adduser -S -D -H -h /app -u 10001 -G dawatrace dawatrace

COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=dawatrace:dawatrace backend /app
# settings.DAWATRACE_VERSION reads ROOT_DIR/VERSION, and ROOT_DIR is the parent
# of /app here, so the canonical version file has to land at /VERSION or the
# running application reports 0.0.0-unknown while the image label says otherwise.
COPY --chown=dawatrace:dawatrace VERSION /VERSION

RUN DJANGO_SETTINGS_MODULE=dawatrace.settings.build \
    DAWATRACE_SECRET_KEY=build-only-staticfiles-not-a-secret \
    DAWATRACE_OBJECT_SIGNING_KEY=build-only-staticfiles-not-a-secret \
    DAWATRACE_ALLOWED_HOSTS=build.invalid \
    python manage.py collectstatic --noinput

# Installation is complete. Do not ship pip's separately vendored libraries or
# build-only setuptools/wheel as runtime attack surface. Neither interpreter
# needs a package installer to serve requests or run migrations.
RUN /opt/venv/bin/python -m pip uninstall --yes pip setuptools wheel \
    && /usr/local/bin/python -m pip uninstall --yes pip setuptools wheel

USER dawatrace
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; request = urllib.request.Request('http://127.0.0.1:8000/api/health/', headers={'Host': os.getenv('TIBATRACE_HOST', 'localhost'), 'X-Forwarded-Proto': 'https'}); urllib.request.urlopen(request, timeout=3)"

CMD ["gunicorn", "dawatrace.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-"]
