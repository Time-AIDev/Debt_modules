"""The debt-crm-lead-sync Cloud Run Job — the durable 2-hour refetch.

A Job and not an HTTP endpoint: the service sits behind IAP on a deployed estate, so
Scheduler → service would have to mint an OIDC token for the IAP client id. A Job
runs this function with no HTTP and no IAP anywhere in the path. The in-process
thread in `pipelines/schedule.py` is the same cadence for a laptop; this is the copy
that survives Cloud Run scaling to zero.

Exit codes: 0 synced · 1 the pull failed (its durable run row says why) · 2 not configured.
"""
import sys

from .. import db
from ..pipelines import schedule, service


def main():
    if not db.configured():
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    if not schedule.odoo_ready():
        print("odoo is not configured: missing ODOO_URL, ODOO_DB, ODOO_LOGIN or ODOO_API_KEY",
              file=sys.stderr)
        return 2
    # run_odoo never raises: it commits a RUNNING run row before the fetch, finishes it
    # FAILED with a code on any failure, and on success lands through the one seam that
    # rebinds the book and bumps the epoch — only when the pull changed something.
    view = service.run_odoo(mode="NEW_ONLY")
    if not view or view.get("state") != "done":
        problem = (view or {}).get("problem") or {}
        code = problem.get("code") or "unknown"
        detail = problem.get("detail") or ""
        print("crm.lead pull failed: %s%s" % (code, (": " + detail) if detail else ""),
              file=sys.stderr)
        return 1
    print("crm.lead landed=%s new=%s changed=%s unchanged=%s retired=%s rejected=%s" % tuple(
        view.get(k) for k in ("landed", "new", "changed", "unchanged", "retired", "rejected")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
