# debt-web — §5.2: nginx on Cloud Run, chosen over GCS+CDN so SPA deep links
# return a real 200 and CSP/cache headers are controlled in one place.
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /src/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
# Runtime config.json (API base URL, Identity Platform key) is injected per
# environment at start — the image is identical in staging and production.
COPY docker-entrypoint.sh /docker-entrypoint.d/40-config.sh
RUN chmod +x /docker-entrypoint.d/40-config.sh
EXPOSE 8080
