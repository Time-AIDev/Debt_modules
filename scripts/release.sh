#!/usr/bin/env bash
# One release entrypoint; dev/staging are always isolated from the production VPS.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
environment="${1:?Usage: scripts/release.sh dev|staging|production <action> [arguments]}"
shift
case "$environment" in
  dev|stg|staging) exec python3 "$ROOT/scripts/run_runtime.py" "$environment" "$@" ;;
  prd|prod|production) exec python3 "$ROOT/infra/vps/release.py" "$@" ;;
  *) printf 'Unknown release environment\n' >&2; exit 2 ;;
esac
