# debt-api — §5.1: 1 vCPU / 1 GiB, gen2, concurrency 40.
FROM python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

RUN adduser --disabled-password --gecos "" --uid 10001 app

COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY app ./app
# The built interface, when the deploy script has placed it here. The bracket glob
# makes this a no-op rather than a build failure when it is absent, so the image
# still builds for an API-only deploy.
COPY stati[c] ./static
# The importer app/imports.py loads at start-up. scripts/ lives ABOVE this build
# context, so deploy_gcp.sh stages it here first. Same bracket-glob trick: absent is
# a no-op, not a build failure.
COPY script[s] ./scripts
# The crm.lead rules file app/pipelines/rules.py reads. docs/ lives ABOVE this build
# context, so deploy_gcp.sh stages it into backend/docs/ first; same bracket-glob
# trick, and the reader carries the checkout layout as its first candidate.
COPY doc[s] ./docs

USER app

# Cloud Run injects PORT. /healthz is the startup and liveness probe target;
# /readyz is used by the LB uptime check and the deploy smoke test, never by Cloud Run
# (Cloud Run has no readiness concept).
ENV PORT=8080
EXPOSE 8080
CMD ["python", "-m", "app.serve_api"]
