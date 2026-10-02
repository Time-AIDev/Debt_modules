#!/usr/bin/env python3
"""Make the six test accounts (login design 2026-09-13 §3.4).

  backend/.venv/bin/python scripts/guides/make_test_accounts.py            # new passwords
  backend/.venv/bin/python scripts/guides/make_test_accounts.py --keep     # re-hash the saved ones

Writes:
  ~/.volt-test-accounts.json   plain passwords, mode 600, OUTSIDE the repo. Read only by
                               build_login_guide.py for the vault copy.
  backend/.env                 AUTH_TEST_ACCOUNTS (hashes only), AUTH_ALLOW_TEST_ACCOUNTS,
                               and AUTH_SESSION_SECRET if it is not already there.
                               NEVER AUTH_MODE: the test suite reads this file.

Prints the usernames, never the passwords.
"""
import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app import auth  # noqa: E402

PLAIN = Path.home() / ".volt-test-accounts.json"
ENV_FILE = ROOT / "backend" / ".env"

ACCOUNTS = (
    ("tester", "ANY", None),
    ("officer.test", "OFFICER", "nantapol"),
    ("supervisor.test", "SUPERVISOR", "settasak"),
    ("manager.test", "MANAGER", "settasak"),
    ("owner.test", "OWNER", "owner"),
    ("ops.test", "OPS", "ops"),
)


def _set_env_lines(path, values):
    lines = path.read_text().splitlines() if path.exists() else []
    keys = set(values)
    kept = [line for line in lines if line.split("=", 1)[0].strip() not in keys]
    kept += ["%s=%s" % (k, v) for k, v in values.items()]
    path.write_text("\n".join(kept) + "\n")


def _write_private(path, text):
    """Write `text` to `path` so the file is never world/group-readable, not even for
    the instant between creation and a trailing chmod: the descriptor is opened with
    mode 0o600 from the first byte, and fchmod is applied too in case `path` already
    existed with a looser mode from an older run."""
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)


def main():
    keep = "--keep" in sys.argv
    if keep:
        plain = json.loads(PLAIN.read_text())
    else:
        plain = {user: secrets.token_urlsafe(12) for user, _role, _officer in ACCOUNTS}
        _write_private(PLAIN, json.dumps(plain, indent=2))

    hashed = {user: {"hash": auth.hash_password(plain[user]), "role": role, "officer": officer}
              for user, role, officer in ACCOUNTS}
    values = {"AUTH_TEST_ACCOUNTS": json.dumps(hashed, separators=(",", ":")),
              "AUTH_ALLOW_TEST_ACCOUNTS": "true"}
    existing = ENV_FILE.read_text() if ENV_FILE.exists() else ""
    if "AUTH_SESSION_SECRET=" not in existing:
        values["AUTH_SESSION_SECRET"] = secrets.token_urlsafe(48)
    _set_env_lines(ENV_FILE, values)

    print("Accounts written (hashes in %s, passwords in %s):" % (ENV_FILE, PLAIN))
    for user, role, officer in ACCOUNTS:
        print("  %-16s %-10s %s" % (user, role, officer or "(chooses)"))


if __name__ == "__main__":
    main()
