# Design — login: Google sign-in, test accounts, and the tester guidebook

**Written 2026-09-13** through `superpowers:brainstorming`, against the tree on branch
`design-team` at `dd1c62e`. Every decision below was ruled on by Arina in that session and is
attributed inline. **Nothing here has been built.**

---

## 0. Standing

A new subsystem of the prototype. On the Requirements Amendment v2.6 §1 ladder it carries no rank
of its own; it implements an instruction given directly by Arina on 2026-09-13:

> "create login page by use google login account and create a test user and password for testing
> all the visible feature from every role."

It is the first step toward SEC-001 (Workspace SSO) and SEC-002 (8h absolute / 30 min idle
sessions) in `docs/Debt_Time_Build_Evidence_Addendum.md:499`. It is **not** SEC-001 in full:
Identity Platform, the blocking function and SEC-003's permission registry stay out of scope.
It changes no domain rule.

---

## 1. What is true of the tree today

**1.1 — No login exists.** Identity is two headers the browser chooses: `X-Volt-Role` and
`X-Volt-Officer` (`frontend/src/api.js:7-13`). The backend reads the role route by route with
`Header(default="OFFICER")`. Only `role_of()` (`routers/today.py:22-24`) checks it against
`ROLES`. Six acts also take `role` from the JSON body (`main.py:1306,1342,1457`,
`journey.py:739,878,1044,1221`).

**1.2 — The cookies that exist are not authentication.** `volt_session` (`main.py:270-300`) keeps
one browser's test data apart from another's. Its own docstring says: "Who someone is comes from
SSO, which this build does not have."

**1.3 — The audit log already marks the gap.** `actor_source` is `HEADER | BODY | NONE`
(`schema.sql:126`), and the audit-log spec (2026-09-11, :205-207, :240) keeps the "claimed" badge
until SSO exists and names `actor_source` as the place SSO plugs in.

**1.4 — Roles differ between the two halves.** The backend accepts five roles
(`routers/today.py:19`: OFFICER, SUPERVISOR, MANAGER, OWNER, OPS). The frontend has four
(`components/role.jsx:11`), and `RoleSwitcher.test.jsx:27` pins exactly those four.

**1.5 — No screen is hidden by role.** Every rail item and route shows for every role. Gating is
inside screens (Today, ReviewQueue, Payments, Recovery, Reports, Dashboard, Settings,
CustomerCase, DataSourcesMigration).

**1.6 — IAP is half-wired.** `scripts/deploy_gcp.sh:84-103` attaches IAP for `domain:volt.co.th`
only if an OAuth consent screen exists, and that screen is console-only and not yet made. No code
reads the IAP header.

**1.7 — The Google token verifier is already a dependency.** `google-auth` is in the uncommitted
`backend/requirements.txt` for the Cloud SQL IAM token, and `google.oauth2.id_token` ships with it.

---

## 2. Decisions (ruled by Arina, 2026-09-13)

| # | Question | Ruling |
|---|---|---|
| L1 | Where Google sign-in happens | **Both layers** — IAP at the door on staging, and the app's own login page |
| L2 | How a Google account gets a role | **Allow-list** — email → role + officer; anyone else is refused |
| L3 | Shape of the test login | **Both** — five accounts locked to one role each, plus one `tester` who can switch |
| L4 | Whether the server trusts role headers | **Only when auth is on** — session wins; with auth unconfigured, today's behaviour |
| L5 | OPS in the UI | **Add OPS to the UI** — the switcher and identity menu show it |
| L6 | Guidebook content | **.docx, and it includes the test passwords** |
| L7 | Guidebook home | **Obsidian vault** and **repo `docs/guides/`** |

**L6 × L7 conflict, resolved by this design (Arina to confirm at spec review).** A password
committed to git stays in history forever and travels with every clone. So one build script makes
**two files from one source**:

- `docs/guides/login-tester-guide.docx`, committed. Every password cell reads "ดูฉบับในคลังเอกสาร
  (vault copy)".
- `…/Debt modules (self build)/06 - Login Tester Guide (with passwords).docx`, vault only. It has
  the real passwords.
- `.gitignore` gains `docs/guides/*with-passwords*`, so a stray local build cannot be committed.

The vault is outside the repo but still a file on disk (and possibly synced). Anyone who can open
the vault copy can sign in to staging, so passwords are rotated with the script in §4.3 whenever
that copy is shared beyond the team.

---

## 3. How it works

### 3.1 The two modes

`AUTH_MODE` decides everything:

| `AUTH_MODE` | Behaviour |
|---|---|
| unset (default) | **Exactly today.** No login page, headers trusted, `actor_source` unchanged. Every existing test runs in this mode. |
| `on` | Login required for every `/v1` route except `/v1/auth/*` and health. Role and officer come from the session. |

This is the same seam rule as the GCP staging spec: *unconfigured* behaves as today, and
*configured but broken* refuses. If `AUTH_MODE=on` but `AUTH_SESSION_SECRET` is missing, the app
refuses to start with a named error. It never quietly falls back to open.

### 3.2 On staging, two gates in a row (L1)

1. **IAP** lets in only `volt.co.th` Google accounts. It is unchanged, already in `deploy_gcp.sh`.
2. **The app's login page** offers:
   - **Sign in with Google.** Google Identity Services puts the button on the page. The server
     verifies the ID token with `google.oauth2.id_token.verify_oauth2_token` against
     `GOOGLE_CLIENT_ID`, requires `email_verified`, then looks the email up in the allow-list.
   - **Username + password**, for test accounts only.

Locally there is no IAP, so only gate 2 exists. On staging a test password is usable only by
someone who already passed IAP with a volt.co.th account. That is accepted: testers are staff.

### 3.3 Backend — `backend/app/auth.py` (new)

| Endpoint | Does |
|---|---|
| `GET /v1/auth/config` | `{mode, google_client_id, password_enabled}` — public, no secrets |
| `POST /v1/auth/google` | `{credential}` → verify, allow-list lookup, set session |
| `POST /v1/auth/password` | `{username, password}` → verify hash, set session |
| `GET /v1/auth/me` | `{subject, kind: GOOGLE\|TEST, role, officer, can_switch, expires_at}` |
| `POST /v1/auth/logout` | clears the session cookie |

**Session cookie `volt_auth`.** A payload `{sub, kind, role, officer, can_switch, iat, seen}`,
base64 and HMAC-SHA256 signed with `AUTH_SESSION_SECRET` (standard library only, no new package).
It is `HttpOnly; SameSite=Lax; Secure` when served over https. **8 h absolute, 30 min idle**
(SEC-002): each request re-signs `seen`. `volt_session` is untouched and keeps its job.

**Passwords.** Stored only as `pbkdf2_sha256` hashes (`hashlib.pbkdf2_hmac`, 600 000 rounds, random
salt) and compared with `hmac.compare_digest`. **Lockout:** 5 failures for one username inside
15 min lock that username for 15 min. The lockout is kept in memory. That is enough for a single
Cloud Run instance, and the limit is written in the code comment.

**Enforcement middleware (L4).** It runs only when `AUTH_MODE=on`, before `tester_session`:

1. No valid session → **401 RFC 9457 problem** `auth-required`, rendered verbatim by the client.
2. It rewrites the request's `X-Volt-Officer` to the session's officer.
3. It rewrites `X-Volt-Role`:
   - a **locked** account → always its own role, whatever was sent;
   - **`tester`** (`can_switch`) → the sent role if it is in `ROLES`, else OFFICER.
4. For a JSON body carrying `role`, the same rule. The body is replaced before the route reads it.
   So `CaseContactDrawer`'s hard-coded `role: 'OFFICER'` (`CaseContactDrawer.jsx:500`) becomes the
   session role, and a manager's contact is recorded as a manager's.

No route changes. Every route still reads the same headers and body; they are just no longer the
browser's to choose.

**Audit.** A request with a session records `actor_source = 'SESSION'` and `actor_claimed = <sub>`.
`schema.sql` swaps the check constraint for one that allows `SESSION`, written idempotently
(`DROP CONSTRAINT IF EXISTS` + `ADD`) so `migrate.py` can re-run it on an existing database.
`AuditLog.jsx` drops the "claimed" badge for `SESSION` rows. Test-account rows carry a
"TEST ACCOUNT" badge instead.

### 3.4 Accounts

**Allow-list (L2).** `AUTH_ALLOWLIST` is JSON, inline or a file path:
`{"settasak@volt.co.th": {"role": "MANAGER", "officer": "settasak"}, …}`. The role must be in `ROLES`
and the officer must be in `officers.registry()`, checked at start-up. A bad entry refuses
start-up with the entry named. An email that is not listed gets a 403 problem `not-on-allow-list`,
in Thai and English, naming who to ask.

**Test accounts (L3).** They load only when `AUTH_ALLOW_TEST_ACCOUNTS=true`. There are six:

| Username | Role | Acts as officer | Switch |
|---|---|---|---|
| `tester` | any of the five | chosen in the switcher | yes |
| `officer.test` | OFFICER | `nantapol` | no |
| `supervisor.test` | SUPERVISOR | `settasak` (registry roles include SUPERVISOR) | no |
| `manager.test` | MANAGER | `settasak` | no |
| `owner.test` | OWNER | `owner` | no |
| `ops.test` | OPS | `ops` — added to `officers.FIXED` with `roles: ["OPS"]` | no |

`officer.test` uses a seeded officer so Today shows real assigned cases. The plan checks that
`nantapol` still owns cases at seed. Adding the `ops` row to `FIXED` changes `/v1/officers`, which
`test_round2.py:295` pins. The plan measures whether that assertion is exact-match or containment
**before** touching it. If exact, the `ops` row is NOT added, and `ops.test` acts as `settasak`
under the OPS role instead.

### 3.5 Frontend

- **`screens/Login.jsx` (new).** Google button (Google Identity Services script, loaded only on
  this page) and a username/password form. Strings go in `i18n-journey.js` (TH + EN), where
  `i18n.test.js` checks parity. Problems from the server show verbatim.
- **Start-up.** `App.jsx` calls `api.authConfig()` once.
  - `mode` off, or the call fails with 404 → render exactly as today.
  - `mode` on and `/v1/auth/me` is 401 → `/login`.
  - Any later 401 `auth-required` from `api.js` → `/login`, keeping the page to return to.
- **Role store.** `ROLES` gains `OPS` (L5). While a session exists, the role store is **seeded from
  `/v1/auth/me`**:
  - a locked account → the switcher and officer select render read-only with the session values;
  - `tester` → works as today.
- **Identity menu** gains "ออกจากระบบ / Sign out". A test session shows a **"TEST ACCOUNT"** badge
  in the top bar, so test activity is never mistaken for real work (the synthetic-data honesty
  idiom).

### 3.6 Deploy and secrets

- `push_secrets.sh` adds `AUTH_SESSION_SECRET`, `AUTH_ALLOWLIST`, `AUTH_TEST_ACCOUNTS` (hashes
  only) and `GOOGLE_CLIENT_ID`.
- `deploy_gcp.sh` sets `AUTH_MODE=on` and `AUTH_ALLOW_TEST_ACCOUNTS=true` for the UAT service,
  mapping the secrets.
- **Arina's new console step:** create an OAuth 2.0 **Web client ID** in `dept-collection-508109`,
  with the Cloud Run URL (and `http://localhost:5173` for local) as an authorised JavaScript
  origin. This sits beside the consent screen step already blocking IAP, and is written into vault
  note `02 - Setup Guide - What You Do`. Until it exists, Google sign-in shows "not configured" and
  password login still works.

---

## 4. The guidebook

### 4.1 Content (Thai first, English under each heading)

1. What the login is, and the two gates on staging.
2. Signing in with Google, step by step, and what "not on the allow-list" means.
3. Signing in with a test account: the six-account table (§3.4) and the passwords (vault copy only).
4. **Per-role checklist**, one table per role, a row for each screen: what you should see, what
   you should be able to do, and what you should be refused. It is taken from the screen gates in
   §1.5 and the backend role checks (`cases.py:819,1173,1203,1246,1387,1401-1402,1424`,
   `routers/settings.py:31-35`, `config.py:210,233`). A tick column lets testers record results.
5. Adding a person to the allow-list.
6. Problems and fixes: the 401 loop, a locked username, the idle timeout, "Google not configured",
   and IAP's own refusal page.

### 4.2 Template

A Volt-style template built in code, since no .docx template exists in the repo:
- A4 page, Sarabun for Thai with a fallback font;
- title page with version and date, and a heading hierarchy;
- tables with a shaded header row, and a footer with the page number and "ข้อมูลทดสอบ / Test data".

The document follows the house doc-versioning habit (a version line and a change table on page 2).

### 4.3 Tooling

- `scripts/guides/build_login_guide.py` makes both files (§2).
- `scripts/guides/make_test_accounts.py`:
  - makes six random 16-character passwords;
  - writes the hashes to `backend/.env` (gitignored) for local use;
  - writes `AUTH_TEST_ACCOUNTS` for `push_secrets.sh`;
  - passes the plain passwords **only** to the vault build.
- Both run in their own venv (`scripts/guides/.venv`, gitignored) with `python-docx`, so the
  backend's requirements do not grow.

---

## 5. Testing

The contract: `./scripts/verify_all.sh` green, at or above the last verified baseline
**761 backend · 577 frontend (49 files) · 31 e2e**. The plan re-measures that on the tree first,
since recorded counts lag. No pinned test is edited without an authorised number.

**New backend tests** (`backend/tests/test_auth_*.py`):
- mode off leaves headers trusted;
- mode on, no cookie → 401 problem;
- Google token valid / invalid / unverified email / not on allow-list (verifier mocked);
- password right / wrong / lockout after 5 / unlock after 15 min (clock injected);
- locked account's sent role and body role overwritten;
- `tester` may switch within `ROLES` only;
- idle and absolute expiry;
- `actor_source = SESSION` written;
- start-up refuses a missing secret or a bad allow-list entry;
- the schema constraint re-applies cleanly.

**New frontend tests:** `Login.test.jsx` (both forms, verbatim problem), start-up redirect when on,
no redirect when off, read-only switcher for a locked session, sign out.

**Known test cost (L5).** `RoleSwitcher.test.jsx:27` asserts
`ROLES toEqual ['OFFICER','SUPERVISOR','MANAGER','OWNER']`. Adding OPS breaks it by design. It
needs **authorised test edit 27** (ledger has 18–26 in the tree; 17 stays reserved): one assertion,
one line, adding `'OPS'`. The plan also re-runs `density.test.jsx` and every file that calls
`setRole` before claiming the price is one line. If more breaks, work stops and the true price
goes to Arina.

---

## 6. Out of scope

- Identity Platform, the blocking function, per-user `iam_user` DB provisioning (SEC-001 proper).
- A default-deny permission registry and row-level security (SEC-003).
- Hiding screens per role. Screens keep their in-screen gates, and the guide documents them.
- An admin screen for the allow-list. It is a JSON secret.
- Reading or cross-checking the IAP JWT inside the app. IAP stays a door only.
