"""Live integrations (R13–R16). Credentials come from backend/.env — gitignored,
filled by hand, NEVER committed and NEVER logged. Only variable NAMES appear in
code, docs and problems; values stay in the environment.
"""
import os
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
_loaded = False


def load_env():
    """A tiny .env reader (KEY=VALUE lines, # comments). Real environment variables
    win over the file, so deployment stays twelve-factor."""
    global _loaded
    if os.environ.get("ENV") == "prd":
        return
    if _loaded:
        return
    _loaded = True
    if not _ENV_PATH.is_file():
        return
    for line in _ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env(key, default=None):
    load_env()
    return os.environ.get(key, default)
