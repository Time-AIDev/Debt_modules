# Allowlist registry release — 2026-10-05

The registry now includes validated AUTH_ALLOWLIST identities even with an empty
customer book. All seven configured accounts and existing role/officer mappings
were preserved. Conflicting registry/allowlist roles fail closed; duplicate
identities are merged. Cache keys track assignment and allowlist identity/role
changes, and returned role arrays are independent copies.

Validation: 82 tests passed, 2 skipped in the isolated auth/registry regression
suite. HTTPS /api/v1/auth/config returned 200. Read-only runtime checks confirmed
all seven configured accounts ACTIVE with unchanged roles, an unlisted address
refused, and nantapol present once as OFFICER. API and worker use the same image
with zero restarts at verification. Actual browser Google sign-in for each account
still requires the account holder; no real Google tokens were used by these tests.
PROD_GO_LIVE_ENABLED remains false. No database or Google OAuth settings changed.

Image: sha256:89eb44c6e1d9ffe5c44f6ed6bbf09eae7eb9d6e93f7fc017aed6f9fab2549c88
Previous image: sha256:f52b6f4630102f277357eb4bece06e80fd2d807a03dcd7b1c659c3a8c1bb222f
Protected configuration backup: /etc/volt-debt/backups/allowlist-20261005
Build recipe: infra/vps/Dockerfile.allowlist (uses the locally retained base image
and copies the changed registry; no dependency changes). Build from repository root:

```sh
docker build --network none -f infra/vps/Dockerfile.allowlist -t volt-debt-api:allowlist-20261005 .
```

Rollback: restore stack.env from the protected backup, then recreate api and
worker with the existing Compose command. Retain api.env and all seven allowlist
entries. The previous image had the missing-officer startup failure, so rollback
restores that prior condition rather than resolving authentication.

This server checkout is a source snapshot; changes here have not been pushed to
the upstream laptop/GitHub repository. Carry the registry change and regression
tests into the canonical source before a later full rebuild replaces this image.
