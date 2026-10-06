# Interface rebuild — 2026-09-19

The interface was rebuilt from scratch to `docs/design/final-ui/Volt Debt Console.html`. The round's
plan and companions were written as a `Plan/` tree; only its `00-FINAL-PLAN.md` was carried into
this repo (now `docs/planning/00-FINAL-PLAN.md`, since rewritten for the 2026-09-21 round).
`Plan/01-endpoint-map.md` … `Plan/05-task-board.md` and `Plan/reference/` (the pre-deletion
`api.js`, `prefs.jsx`, `role.jsx`, `auth.jsx`, `AuthGate.jsx`, `googleScript.js` from commit
`eac7865`) are not in this repo; recover them from the round's own archive if needed.

## Evidence in this folder

- `evidence/*.png` — `scripts/probe_rebuild.mjs` output: 13 lenses × TH/light and EN/dark at 1440 px,
  every view console-error free when run against the dev server with the API on :8000.

## How to re-run the evidence

```bash
cd backend && .venv/bin/uvicorn app.main:app --port 8000        # API
cd frontend && npx vite --port 5173 --strictPort                # UI (proxies /api)
node scripts/probe_rebuild.mjs                                  # screenshots + console check
./scripts/verify_all.sh                                         # backend + frontend + black-box
```

## Follow-ups recorded, not silently dropped

- The manager-review queue (`GET /v1/manager-review`) has no dedicated screen in this pass.
- Pipeline delivery/install-outcome controls are wired in `api.js` but not surfaced yet.
- A blind UAT round with a person has not been run on this build; the protocol is
  `UAT_Blind_Round_Protocol.md` in the Drive decision records, not in this repo.
