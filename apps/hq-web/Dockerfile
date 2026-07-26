FROM node:20-alpine AS builder

WORKDIR /workspace
COPY package.json package-lock.json ./
COPY apps/hq-web/package.json apps/hq-web/package.json
COPY apps/pos-android/package.json apps/pos-android/package.json
COPY apps/pos-windows/package.json apps/pos-windows/package.json
COPY packages/shared/package.json packages/shared/package.json
RUN npm ci --ignore-scripts

COPY apps/hq-web apps/hq-web
RUN npm --workspace @dawatrace/hq-web run build

FROM nginx:1.27-alpine

ARG DAWATRACE_VERSION=0.1.0-alpha.1
ARG SOURCE_REVISION=unknown
ARG BUILD_TIME=unknown

LABEL org.opencontainers.image.title="TibaTrace HQ Web" \
      org.opencontainers.image.vendor="Esenai Group Ltd" \
      org.opencontainers.image.version="${DAWATRACE_VERSION}" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.created="${BUILD_TIME}"

COPY apps/hq-web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /workspace/apps/hq-web/dist /usr/share/nginx/html

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q -O - http://127.0.0.1:8080/healthz || exit 1
