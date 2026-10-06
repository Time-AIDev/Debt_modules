# debt-web — §5.2: nginx on Cloud Run, chosen over GCS+CDN so SPA deep links
# return a real 200 and CSP/cache headers are controlled in one place.
FROM node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS build
WORKDIR /src
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.30.5-alpine@sha256:0985e772fb9f729e6fa0980da05fca5d9c468e870eed43071545afa9d2e27d94
RUN apk upgrade --no-cache
ARG VOLT_GIT_REVISION=unknown
LABEL org.opencontainers.image.revision=$VOLT_GIT_REVISION
COPY --from=build /src/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
# Runtime config.json (API base URL, Identity Platform key) is injected per
# environment at start — the image is identical in staging and production.
COPY docker-entrypoint.sh /docker-entrypoint.d/40-config.sh
RUN chmod +x /docker-entrypoint.d/40-config.sh
EXPOSE 8080
