#!/usr/bin/env bash
# Thin wrapper so the harness is one command from a shell. The work is in
# pg_local.py, which needs the backend venv because that is where pgserver lives.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT/backend/.venv/bin/python" "$ROOT/scripts/pg_local.py" "$@"
