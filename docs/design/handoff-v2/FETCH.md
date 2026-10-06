# Fetch record

Imported from Claude Design project `800e8d00-edf4-4954-954b-773f7f97ceb0` on 2026-09-17T15:03:06.364Z.

Re-run with:

```sh
node scripts/design_mcp_fetch.mjs --project 800e8d00-edf4-4954-954b-773f7f97ceb0 --out docs/design/handoff-v2
```

Auth: the `designOauth` grant Claude Code stored when `/design-login` was last run
(macOS keychain item `Claude Code-credentials`); override with `DESIGN_MCP_TOKEN`.
Text files are paged through `read_file` (256 KiB cap per call) and rebuilt
byte-exact; binaries come through `render_preview` serve URLs.

| file | bytes | sha256 | listing |
|---|---|---|---|
| `Volt Debt - Final v2.dc.html` | 273567 | `c628c1588f366ab0…` | 273567 |
| `support.js` | 69150 | `8fe7df74405f3c55…` | 69150 |
| `README.md` | 18697 | `7e42c43338afb627…` | 18697 |
| `KICKOFF_PROMPT.md` | 3667 | `f36193dccc43b820…` | 3667 |
| `assets/volt-logo.png` | 12186 | `f34a5339f2e6395c…` | 6416 |
| `screenshots/01-screen.png` | 38325 | `4adbddd27b4d888a…` | 32554 |
| `screenshots/02-screen.png` | 38325 | `806972684541eb99…` | 32554 |
| `screenshots/03-screen.png` | 46874 | `036ce3fdd014c221…` | 41103 |
| `screenshots/04-screen.png` | 30260 | `92f662a90505b5dc…` | 24489 |
| `screenshots/05-screen.png` | 46932 | `a4443fb51fda3bf4…` | 41161 |
| `screenshots/06-screen.png` | 33233 | `4a2ece28f5c51a34…` | 27462 |
| `screenshots/07-screen.png` | 36357 | `0c3fcc71c03e0f27…` | 30586 |
| `screenshots/08-screen.png` | 37440 | `aae20d820c796139…` | 31669 |
| `screenshots/09-screen.png` | 37259 | `7d41df8db0f34dea…` | 31488 |
| `screenshots/10-screen.png` | 36846 | `a87f510fe760314f…` | 31075 |
| `screenshots/11-screen.png` | 36429 | `56a7b6032adb0584…` | 30658 |
| `screenshots/12-screen.png` | 35377 | `d24f737119d82dbf…` | 29606 |
| `screenshots/13-screen.png` | 35222 | `46108dca6e148518…` | 29451 |
| `screenshots/14-screen.png` | 36417 | `8028de3ac9a2e150…` | 30646 |
| `screenshots/15-screen.png` | 46874 | `bf79211068c84661…` | 41103 |

Local edits to these files are not pushed back: the MCP write methods are never called by this script.
