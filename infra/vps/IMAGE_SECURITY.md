# Reviewed infrastructure image recipes

The canonical shared runtime uses `Dockerfile.db.no_xml` and
`Dockerfile.scanner`. Promote their tested immutable image IDs together with the
API/web artifacts; never replace a PostgreSQL volume or change its major version
as part of image promotion.

On 2026-10-06 the tested database was PostgreSQL **16.15**, built from the official
source archive with SHA-256
`c1575341fa7bd40f5274ea465b34390f4dc64cdd0770af327005caaeb9f6b7ed`.
Its base remains Debian 13.7 with glibc 2.41, ICU 76 and `en_US.utf8`/UTF8.
OpenSSL, LZ4/ZSTD, PL/pgSQL and the non-XML contrib extension set were retained.
The official PostgreSQL entrypoint and UID/GID 999 remain in use.

SQL XML/XSLT and LLVM JIT are intentionally disabled. The current application has
no SQL XML calls, and the read-only production inventory found no XML columns or
extensions. Removing these optional features removes libxml2/LLVM from the
runtime instead of applying an unsafe library ABI change. SQL XML requests fail
explicitly and `pg_jit_available()` reports false. Future large database queries
may lose JIT acceleration; that performance case has not been benchmarked.

`Dockerfile.db` retains the official full-feature PostgreSQL 16 package and
rebuilds gosu, but still contains vendor-unfixed libxml2. It is a separate reviewed
fallback, not the canonical hardened profile. Keep the previous production image
available for rollback; no automatic physical database downgrade is performed.

Both recipes rebuild **gosu 1.19** using **Go 1.27.1** from upstream commit
`6456aaa0f3c854d199d0f037f068eb97515b7513`, with source archive SHA-256
`33d7537d588ea49458b9509bcf4554bdf5ceacc66da71e5caa1058ea3b689c3b`.
The scanner retains ClamAV **1.5.4** and updates Alpine packages, including PCRE2
**10.49-r0** and OpenSSL libraries **3.5.9-r0**.

The candidate passed an isolated synthetic existing-cluster test and a fresh
initialization/restore test, with one 256 MiB database at a time, no network or
published ports. Checks cover physical cluster reuse, locales/ICU index ordering,
Thai text, JSONB, exact decimal money, schema version 2, append-only audit/history,
non-XML contrib versions, compressed gzip/xz/zstd init files and dump/restore.
All PostgreSQL executable/shared-module ELF dependencies were checked.

```sh
python3 -O scripts/check_postgres_image.py \
  --candidate-image 'sha256:<tested image ID>' \
  --output /private/review/db-image-smoke.json
python3 scripts/image_security_gate.py \
  reports/production-20261006/db-no-xml-image-audit.json \
  reports/production-20261006/scanner-image-audit.json
```

The full Trivy scan found **0 critical and 0 fixable high/critical findings** in
the canonical database, with **44 vendor-unfixed high findings still recorded**.
The scanner had no high/critical findings. A passing gate means no fixable
high/critical findings; it does not mean zero CVEs. Go standard-library findings
receive the same gate as other dependencies and are never excluded as supposedly
unreachable.

The PostgreSQL source build is not an apt package. Its exact version, archive
hash, build flags and tested image ID are therefore recorded explicitly in
`db-no-xml-build-provenance.json` and as a component in the CycloneDX SBOM. Absence
from the apt package inventory does not establish absence of PostgreSQL CVEs.

The original libxml2 backport was rejected after all 40 Debian maintainer patches
were applied: the exact upstream refactor failed 10 patch hunks and changes public
structure layouts. No fixed VEX statement is claimed for that library. The
[Debian tracker](https://security-tracker.debian.org/tracker/CVE-2026-6653) classifies
the unresolved distro issue as `no-dsa`/minor, while Trivy reports it as critical.
The canonical image removes the component; the fallback preserves that remaining
risk in its scan.

Artifacts in `reports/production-20261006/` include full package-only vulnerability
JSON, CycloneDX SBOMs, isolated smoke evidence, source provenance and the rejected
backport dry-run. Refresh the vulnerability database and rescan exact candidate
images before subsequent releases.
