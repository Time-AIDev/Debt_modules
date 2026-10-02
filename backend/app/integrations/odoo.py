"""Odoo UAT integration (R13/R14) — the JSON-RPC client the crm.lead pull uses
(app/pipelines), plus discovery and status.

It READS Odoo only; nothing is ever written back (R14 — a manual adjustment is a
local override with provenance, never a write into a shared UAT system). The
sale.order sync, its landing rows and its snapshot rung were removed on 2026-09-25
(fix-all, Arina's decision 6): "Sync Odoo" runs the crm.lead pull.
"""
import httpx

from . import env

REQUIRED_ENV = ("ODOO_URL", "ODOO_DB", "ODOO_LOGIN", "ODOO_API_KEY")

# Discovery probes these; whatever holds data decides the mapping (R13: "discover
# at runtime" — chosen over assuming the Odoo modules).
CANDIDATE_MODELS = (
    "res.partner", "sale.order", "crm.lead", "account.move",
    "project.project", "stock.picking", "product.product",
)

TIMEOUT = 8.0


class OdooError(Exception):
    pass


class NotConfigured(OdooError):
    def __init__(self):
        super().__init__("Odoo credentials are not configured")
        self.missing = [k for k in REQUIRED_ENV if not env(k)]


def _config():
    missing = [k for k in REQUIRED_ENV if not env(k)]
    if missing:
        raise NotConfigured()
    return {k: env(k) for k in REQUIRED_ENV}


def _rpc(url, service, method, args):
    payload = {"jsonrpc": "2.0", "method": "call",
               "params": {"service": service, "method": method, "args": args}, "id": 1}
    response = httpx.post(url.rstrip("/") + "/jsonrpc", json=payload, timeout=TIMEOUT)
    response.raise_for_status()
    body = response.json()
    if body.get("error"):
        message = body["error"].get("data", {}).get("message") or body["error"].get("message")
        raise OdooError(message or "Odoo returned an error")
    return body.get("result")


def _login(config):
    uid = _rpc(config["ODOO_URL"], "common", "authenticate",
               [config["ODOO_DB"], config["ODOO_LOGIN"], config["ODOO_API_KEY"], {}])
    if not uid:
        raise OdooError("Odoo refused the login — check ODOO_LOGIN / ODOO_API_KEY")
    return uid


def _execute(config, uid, model, method, args, kwargs=None):
    return _rpc(config["ODOO_URL"], "object", "execute_kw",
                [config["ODOO_DB"], uid, config["ODOO_API_KEY"], model, method,
                 args, kwargs or {}])


def discovery():
    """Connect, list which candidate models actually hold data, and propose the
    mapping. Read-only."""
    config = _config()
    uid = _login(config)
    models = []
    for model in CANDIDATE_MODELS:
        try:
            count = _execute(config, uid, model, "search_count", [[]])
            models.append({"model": model, "records": count})
        except OdooError as exc:
            models.append({"model": model, "records": None, "error": str(exc)})
    return {
        "connected": True,
        "login_uid": uid,
        "models": models,
        "proposed_mapping": {
            "orders": "sale.order (name, partner_id, amount_total, state, date_order)",
            "customers": "res.partner (name, phone, mobile, email, city)",
        },
    }


def snapshot_meta():
    """The last crm.lead pull's source block — when, which door, which run — or None
    without a database or before the first pull. Read from the slim run row: a
    status read must not decode a run's whole meta."""
    from .. import db, landing
    if not db.configured():
        return None
    conn = db.connect()
    try:
        run = landing.lead_run_slim(conn)
    finally:
        conn.close()
    if not run:
        return None
    finished = run.get("finished_at")
    return {"system": "Odoo UAT", "url_env": "ODOO_URL", "db_env": "ODOO_DB",
            "synced_at": finished.isoformat() if finished else None,
            "door": (run.get("meta") or {}).get("door"), "run_id": run.get("id")}


def status():
    missing = [k for k in REQUIRED_ENV if not env(k)]
    snapshot = snapshot_meta()
    return {
        "integration": "Odoo UAT",
        "configured": not missing,
        "missing_env": missing,       # names only — values never leave the env
        "snapshot": snapshot,
        "fallback_chain": ["ODOO", "SHEET_FIXTURES"],     # no snapshot rung since 2026-09-25
    }
