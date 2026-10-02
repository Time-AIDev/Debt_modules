#!/bin/sh
set -e
cat > /usr/share/nginx/html/config.json <<JSON
{
  "apiBaseUrl": "${API_BASE_URL:-/api}",
  "identityPlatformApiKey": "${IDP_API_KEY:-}",
  "env": "${ENV:-local}"
}
JSON
