#!/usr/bin/env python3
"""Black-box end-to-end check for the Volt Debt prototype.

Standard library only (urllib, json, argparse). It does not import the backend, does
not need the backend virtualenv, and starts nothing: point it at a running API.

Every check asserts a RULE, not a 200. The rules are the ones the design set argues
for, and the ones the 25-08 cross-artefact audit found broken in fixture data while
the prose stated them correctly. Most of all D13: a permit hold pauses the FEE and
does NOT pause the CLOCK. Check 9 fails loudly if anyone "fixes" that contract to
DPD 0, because that is the defect, not the fix.

Exit codes
  0  every check passed
  1  at least one check failed
  2  the API is not answering (or stopped answering mid-run)
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from decimal import Decimal

# A money string the API may print. Two decimal places, always: satang precision is
# part of the contract, so "18135.0" or a float that arrived as 18135.000000001 is a
# failure even when it compares equal.
MONEY = re.compile(r"^-?\d+\.\d{2}$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PROBLEM_JSON = "application/problem+json"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def slot_day():
    """The synthetic calendar day the contact checks (13 and 14) run on.

    The daily contact lock lives in the API process, so a hard-coded date would let
    check 13 pass once and fail on every re-run against a server that is still up.
    Deriving the day from the clock gives each run its own untouched slot without
    softening the rule under test. The API takes the moment from the request body,
    so this costs nothing and touches no other check: the today list resolves locks
    against the configured business date, never against this one.
    """
    return date(2030, 1, 1) + timedelta(days=int(time.time()) % 200000)


SLOT_DAY = slot_day()


# --- transport -------------------------------------------------------------------

class CheckFailed(Exception):
    """A rule was broken. The message says which rule, in words."""


class Unreachable(Exception):
    """The API is not there. Not a failed check - a failed run."""


class Response:
    def __init__(self, label, status, headers, body):
        self.label = label
        self.status = status
        self.headers = headers
        self.body = body

    @property
    def content_type(self):
        return (self.headers.get("content-type") or "").split(";")[0].strip()

    def json(self):
        try:
            return json.loads(self.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise CheckFailed(
                "%s did not return JSON. First 160 bytes: %r" % (self.label, self.body[:160])
            )


class Api:
    def __init__(self, base_url, timeout):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        # A localhost smoke test must never be routed through an inherited proxy.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        # Journey state (PTPs, reviews, board moves) is PER TESTER SESSION, keyed on
        # the volt_session cookie; a deployed estate also signs in with volt_auth.
        # Without holding them, every request lands in a fresh sandbox and a PTP
        # created by one call is gone by the next — so this client keeps every cookie
        # it is given, like the one browser it stands in for. (It used to keep only
        # the first set-cookie when that one was volt_session; on staging the first is
        # volt_auth, so the login succeeded and every check after it answered 401 —
        # 2026-09-21.)
        self.cookies = {}

    def call(self, method, path, body=None, extra_headers=None,
             raw_body=None):
        label = "%s %s" % (method, path)
        data = None
        headers = {"accept": "application/json, " + PROBLEM_JSON}
        if self.cookies:
            headers["cookie"] = "; ".join("%s=%s" % kv for kv in self.cookies.items())
        if raw_body is not None:
            # A file is sent as the body itself — the shape routers/imports.py and
            # routers/pipelines.py both take. No multipart anywhere in this service.
            data = raw_body
        elif body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["content-type"] = "application/json"
        if extra_headers:
            headers.update(extra_headers)
        request = urllib.request.Request(
            self.base + path, data=data, headers=headers, method=method
        )
        try:
            handle = self.opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            # 4xx and 5xx are answers here, not accidents: half these checks assert a
            # refusal, and a refusal is the product working.
            self._keep_cookie(exc.headers)
            return Response(label, exc.code, exc.headers, exc.read())
        except urllib.error.URLError as exc:
            raise Unreachable("%s %s - %s" % (method, self.base + path, exc.reason))
        except OSError as exc:
            raise Unreachable("%s %s - %s" % (method, self.base + path, exc))
        with handle:
            self._keep_cookie(handle.headers)
            return Response(label, handle.getcode(), handle.headers, handle.read())

    def _keep_cookie(self, headers):
        get_all = getattr(headers, "get_all", None)
        raw = (get_all("set-cookie") or []) if get_all else [headers.get("set-cookie") or ""]
        for header in raw:
            pair = (header or "").split(";", 1)[0].strip()
            if "=" not in pair:
                continue
            name, _, value = pair.partition("=")
            self.cookies[name.strip()] = value.strip()

    def login(self, username, password):
        """Sign in once for a deployed estate (AUTH_MODE=on).

        A local run has login off and every route answers without this. On staging
        the first request would 302/401, so the client signs in exactly the way the
        login page does and keeps the `volt_session` cookie the same way the browser
        does. Returns True on 200, False on any refusal (wrong password, lockout,
        login off)."""
        response = self.call("POST", "/v1/auth/password",
                             {"username": username, "password": password})
        return response.status == 200

    def get(self, path):
        return self.call("GET", path)

    def post(self, path, body, extra_headers=None):
        return self.call("POST", path, body, extra_headers=extra_headers)

    def delete(self, path, body=None):
        return self.call("DELETE", path, body)


# --- the check registry ------------------------------------------------------------

CHECKS = []


class Spec:
    def __init__(self, number, name, proves, fn):
        self.number = number
        self.name = name
        self.proves = proves
        self.fn = fn


def check(number, name, proves):
    def register(fn):
        CHECKS.append(Spec(number, name, proves, fn))
        return fn
    return register


def _show(value):
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(value)


class Ctx:
    """What a check writes to: assertions in, one 'proves' line and evidence out."""

    def __init__(self, spec):
        self.evidence = []
        # The registered line, which a check may replace with one carrying the run's
        # real numbers: `ctx.proves = "..."`.
        self.proves = spec.proves

    def note(self, text):
        self.evidence.append(text)

    def require(self, ok, message):
        if not ok:
            raise CheckFailed(message)

    def equal(self, actual, expected, what):
        if actual != expected:
            raise CheckFailed("%s: expected %s, got %s" % (what, _show(expected), _show(actual)))

    def status(self, response, expected, why=""):
        if response.status != expected:
            raise CheckFailed(
                "%s answered %d, expected %d%s"
                % (response.label, response.status, expected, (" - " + why) if why else "")
            )

    def problem(self, response, code, error_id=None):
        """Every refusal is RFC 9457 problem+json, and `code` is the ONLY field a
        client may branch on. `detail` is explicitly outside the compatibility
        contract, so nothing here reads it."""
        self.equal(response.content_type, PROBLEM_JSON,
                   "%s content-type (a refusal must be problem+json)" % response.label)
        payload = response.json()
        self.equal(payload.get("code"), code, "%s code" % response.label)
        if error_id:
            self.equal(payload.get("error_id"), error_id, "%s error_id" % response.label)
        self.require((payload.get("message_th") or "").strip(),
                     "%s carries no message_th - a Thai sentence is always present" % response.label)
        self.require(isinstance(payload.get("errors"), list),
                     "%s errors must be an array, empty when not applicable, never absent"
                     % response.label)
        self.require(isinstance(payload.get("extensions"), dict),
                     "%s extensions must be an object, empty when not applicable" % response.label)
        return payload


# --- shared fetches ------------------------------------------------------------------

def today_list(api):
    response = api.get("/v1/today-list")
    if response.status != 200:
        raise CheckFailed("GET /v1/today-list answered %d, expected 200" % response.status)
    return response.json()


def exception_rows(api):
    response = api.get("/v1/dashboards/exceptions?population_filter=ALL_OPEN")
    if response.status != 200:
        raise CheckFailed(
            "GET /v1/dashboards/exceptions?population_filter=ALL_OPEN answered %d, expected 200"
            % response.status
        )
    return response.json().get("rows") or []


def any_contract_uid(api):
    rows = exception_rows(api)
    if not rows:
        raise CheckFailed("there is no contract in the book to act on")
    return rows[0]["contract_uid"]


def contact_body(customer_uid, hour, direction, disposition):
    return {
        "customer_uid": customer_uid,
        "at": "%sT%02d:00:00+07:00" % (SLOT_DAY.isoformat(), hour),
        "channel": "PHONE",
        "direction": direction,
        "disposition": disposition,
        "officer": "e2e-check",
        "role": "OFFICER",
    }


def slot_customer(api):
    """Prefer the multi-contract customer: the daily lock is keyed on the PERSON, and
    a customer holding several contracts is the only one that can prove it."""
    items = today_list(api)["items"]
    if not items:
        raise CheckFailed("the today list is empty - there is no customer to contact")
    multi = [i for i in items if i["customer"].get("contract_count", 1) > 1]
    return (multi or items)[0]["customer"]


# --- 1-2  the platform ----------------------------------------------------------------

@check(1, "the API answers",
       "livez and readyz answer, and readyz names the ledger day every figure below is measured on")
def check_liveness(api, ctx):
    # /livez, not /healthz: Google's front end reserves the latter on *.run.app and
    # 404s it before the container sees the request (2026-09-21). Both are the same
    # handler in app/main.py.
    health = api.get("/livez")
    ctx.status(health, 200)
    ctx.equal(health.json().get("status"), "ok", "/livez status")

    ready = api.get("/readyz")
    ctx.status(ready, 200)
    payload = ready.json()
    ctx.equal(payload.get("status"), "ready", "/readyz status")
    business_date = payload.get("business_date") or ""
    ctx.require(ISO_DATE.match(business_date),
                "/readyz must name a business_date as YYYY-MM-DD, got %s" % _show(business_date))
    ctx.proves = ("the surface is up and names its ledger day %s - every figure below is measured "
                  "on that date, not on the wall clock" % business_date)
    ctx.note("business_date %s" % business_date)


@check(2, "the URL version does not move with the document",
       "the document is 2.x while the addresses stay /v1 - v2.x change is additive, /v2 would break clients")
def check_version(api, ctx):
    response = api.get("/v1/meta/version")
    ctx.status(response, 200)
    payload = response.json()
    ctx.equal(payload.get("url_version"), "v1", "url_version")
    document_version = str(payload.get("document_version") or "")
    ctx.require(document_version.startswith("2."),
                "document_version must be a 2.x version, got %s - if the document really went "
                "to 3.x the surface still stays /v1, so fix the fixture, not this check"
                % _show(document_version))
    ctx.proves = ("the document is at %s while the addresses stay /v1 - every v2.x change is "
                  "additive, minting /v2 would be a breaking change" % document_version)
    ctx.note("url_version v1, document_version %s" % document_version)


# --- 3-6  screen 01, the today list -----------------------------------------------------

@check(3, "the today list is grouped by customer, never by contract",
       "one row per person: a customer holding several contracts is called once, not once per contract")
def check_grouped_by_customer(api, ctx):
    items = today_list(api)["items"]
    ctx.require(items, "the today list is empty - nothing to group")

    uids = [i["customer"]["uid"] for i in items]
    duplicated = sorted(set(u for u in uids if uids.count(u) > 1))
    ctx.require(not duplicated,
                "a customer uid appears on more than one row (%s) - the list is keyed on "
                "contracts and that customer will be called twice today" % ", ".join(duplicated))

    contracts = sum(i["customer"].get("contract_count", 0) for i in items)
    multi = [i for i in items if i["customer"].get("contract_count", 1) > 1]
    ctx.require(multi,
                "no customer in the book holds more than one contract, so this rule is untested - "
                "restore the two-contract fixture rather than deleting the check")

    # The count must be the truth, not a label: read the contracts back.
    sample = multi[0]["customer"]
    rows = api.get("/v1/customers/%s/contracts" % sample["uid"]).json().get("contracts") or []
    ctx.equal(len(rows), sample["contract_count"],
              "%s contract_count against /v1/customers/{uid}/contracts" % sample["customer_no"])

    ctx.proves = ("one row per customer, never per contract - %d contracts collapse into %d rows, "
                  "so nobody is contacted twice in a day" % (contracts, len(items)))
    ctx.note("%s holds %d contracts and occupies exactly one row"
             % (sample["customer_no"], sample["contract_count"]))


@check(4, "every band code carries the band set that defines it",
       "a bucket code alone no longer identifies a band - two sets exist and both use the same codes")
def check_band_set_code(api, ctx):
    items = today_list(api)["items"]
    banded = [i for i in items if i.get("aging_bucket")]
    ctx.require(banded, "no item carries an aging_bucket, so the pairing rule is untested")
    for item in banded:
        ctx.require(item.get("band_set_code"),
                    "%s shows aging_bucket %s with no band_set_code - the code alone does not "
                    "identify a band" % (item["customer"]["customer_no"], item["aging_bucket"]))
    sets = sorted(set(i["band_set_code"] for i in banded))
    ctx.proves = ("all %d banded rows carry band_set_code (%s) - the bucket code alone does not "
                  "identify a band" % (len(banded), ", ".join(sets)))


@check(5, "the priority counts reconcile to the list",
       "the header count and the rows beneath it cannot disagree")
def check_counts_by_priority(api, ctx):
    payload = today_list(api)
    items = payload["items"]
    counts = (payload.get("meta") or {}).get("counts_by_priority")
    ctx.require(isinstance(counts, dict) and counts, "meta.counts_by_priority is missing or empty")
    for key, value in counts.items():
        ctx.require(isinstance(value, int), "counts_by_priority[%s] is not a whole number: %s"
                    % (key, _show(value)))
    total = sum(counts.values())
    ctx.equal(total, len(items), "counts_by_priority total against the item count")
    ctx.proves = ("counts_by_priority sums to %d and the list holds %d rows - the header cannot "
                  "disagree with what is under it" % (total, len(items)))
    ctx.note("counts_by_priority %s" % _show(counts))


@check(6, "aggregate_overdue reconciles to the contracts beneath it",
       "the customer total equals the sum of that customer's contract arrears, to the satang")
def check_rollup_reconciles(api, ctx):
    items = today_list(api)["items"]
    ctx.require(items, "the today list is empty - nothing to reconcile")
    worked = None
    for item in items:
        customer = item["customer"]
        aggregate = str(item.get("aggregate_overdue"))
        ctx.require(MONEY.match(aggregate),
                    "%s aggregate_overdue %s is not a two-decimal money string - satang "
                    "precision is part of the contract" % (customer["customer_no"], _show(aggregate)))

        rows = api.get("/v1/customers/%s/contracts" % customer["uid"]).json().get("contracts") or []
        total = Decimal("0.00")
        parts = []
        for row in rows:
            arrears = str(row.get("arrears"))
            ctx.require(MONEY.match(arrears),
                        "%s %s arrears %s is not a two-decimal money string"
                        % (customer["customer_no"], row.get("uid"), _show(arrears)))
            total += Decimal(arrears)
            parts.append(arrears)

        ctx.require(Decimal(aggregate) == total,
                    "%s aggregate_overdue %s does not reconcile to its contracts %s = %s. "
                    "A rolled-up total that does not tie out to the rows beneath it is the "
                    "defect class the 25-08 audit found."
                    % (customer["customer_no"], aggregate, " + ".join(parts) or "(none)", total))
        if worked is None or len(parts) > 1:
            worked = "%s %s = %s" % (customer["customer_no"], aggregate, " + ".join(parts) or "0.00")

    ctx.proves = ("every customer total ties out to its contracts to the satang, compared as "
                  "Decimal and never as float (%d customers checked)" % len(items))
    ctx.note(worked)


# --- 7-9  screen 03, the exception dashboard ---------------------------------------------

@check(7, "the exception dashboard refuses an undefined population",
       "there is no implicit whole-book default: an undefined KPI is refused, not rendered")
def check_population_filter_unset(api, ctx):
    response = api.get("/v1/dashboards/exceptions")
    ctx.status(response, 422, "an unfiltered dashboard must refuse, not guess")
    payload = ctx.problem(response, "population_filter_unset", "DEBT-KPI-0422")
    config_key = payload["extensions"].get("config_key")
    ctx.require(config_key,
                "extensions.config_key must name the setting that would have supplied a default, "
                "otherwise nobody knows what to configure")
    ctx.proves = ("no implicit whole-book default - an undefined population is refused as "
                  "problem+json (config_key %s), never rendered as a number" % config_key)
    ctx.note("422 %s / %s, message_th %d chars, errors[] present"
             % (payload["code"], payload["error_id"], len(payload["message_th"])))


@check(8, "the same dashboard answers once the population is named",
       "the refusal is about the missing filter, not a dead endpoint")
def check_population_filter_set(api, ctx):
    response = api.get("/v1/dashboards/exceptions?population_filter=ALL_OPEN")
    ctx.status(response, 200)
    payload = response.json()
    ctx.equal(payload.get("population_filter"), "ALL_OPEN", "the filter is echoed back")
    rows = payload.get("rows")
    ctx.require(isinstance(rows, list) and rows,
                "ALL_OPEN returned no rows - the endpoint answers but says nothing")
    ctx.proves = ("naming the population turns the refusal into %d rows - check 7 refuses the "
                  "missing filter, not the endpoint" % len(rows))


@check(9, "a permit hold pauses the fee and never the clock",
       "D13: PERMIT_HOLD stops the fee accruing while days_past_due keeps running - DPD 0 here is the defect")
def check_permit_hold(api, ctx):
    rows = exception_rows(api)
    held = [r for r in rows if r.get("fee_state") == "PERMIT_HOLD"]
    ctx.require(held,
                "no PERMIT_HOLD contract is in the book. The fixture that proves D13 has gone "
                "missing, so the rule is now untested - restore it rather than deleting this check")
    for row in held:
        dpd = row.get("days_past_due")
        ctx.require(isinstance(dpd, int) and dpd > 0,
                    "%s is PERMIT_HOLD with days_past_due %s. A permit hold pauses the FEE and "
                    "does NOT pause the CLOCK (D13). Drawing this contract at 0 is the exact "
                    "defect the 25-08 audit found on two screens - if someone has just 'fixed' "
                    "it to 0, that change is the bug." % (row.get("contract_uid"), _show(dpd)))
        ctx.require(row.get("fee_paused") is True,
                    "%s is PERMIT_HOLD but fee_paused is %s - the other half of D13 is that the "
                    "fee really does stop" % (row.get("contract_uid"), _show(row.get("fee_paused"))))
    sample = held[0]
    ctx.proves = ("PERMIT_HOLD pauses the FEE and never the CLOCK - %s is fee_paused at DPD %d; "
                  "DPD 0 here would be the defect, not the fix"
                  % (sample["contract_uid"], sample["days_past_due"]))
    ctx.note("%d permit-held contract(s): %s"
             % (len(held), ", ".join("%s DPD %s" % (r["contract_uid"], r["days_past_due"]) for r in held)))


# --- 10-12  screen 02, the contract card ---------------------------------------------------

@check(10, "the summary leads with what is payable today",
       "payable-today is the first key, and penalty stays four figures - decided (ruling 87 "
       "the rate, ruling 88 the grace) and never netted")
def check_contract_summary(api, ctx):
    uids = [r["contract_uid"] for r in exception_rows(api)]
    ctx.require(uids, "no contracts to summarise")
    # A netted penalty total is forbidden (TC-COL-053): one number hides which part of it
    # is billed and which part nobody has agreed to bill.
    banned_exact = set(["net", "netted", "net_amount", "balance", "amount", "sum", "outstanding"])
    for uid in uids:
        response = api.get("/v1/contracts/%s/summary" % uid)
        ctx.status(response, 200)
        payload = response.json()
        keys = list(payload.keys())
        ctx.require(keys and keys[0] == "total_arrears_payable_today",
                    "%s summary leads with %s. An officer must see what is payable today first; "
                    "a response that leads with the next instalment fails TC-COL-052."
                    % (uid, _show(keys[0] if keys else None)))

        penalty = payload.get("accrued_penalty")
        ctx.require(isinstance(penalty, dict), "%s carries no accrued_penalty block" % uid)
        for field in ("accrued_unbilled", "billed", "paid", "waived"):
            ctx.require(field in penalty,
                        "%s accrued_penalty has no %s - the four figures are reported separately "
                        "and never netted into one" % (uid, field))
            ctx.require(MONEY.match(str(penalty[field])),
                        "%s accrued_penalty.%s is %s, not a two-decimal money string"
                        % (uid, field, _show(penalty[field])))
        netted = sorted(k for k in penalty if "total" in k.lower() or k.lower() in banned_exact)
        ctx.require(not netted,
                    "%s accrued_penalty carries a netted figure %s - accrued, billed, paid and "
                    "waived must never collapse into one number" % (uid, ", ".join(netted)))
        ctx.require(penalty.get("is_indicative") is False,
                    "%s accrued_penalty.is_indicative is %s. Ruling 87 decided CF1 (the rate), so "
                    "penalty figures are no longer indicative and a PEAK draft may be raised from them."
                    % (uid, _show(penalty.get("is_indicative"))))
        ctx.equal(penalty.get("decided_by_ruling"), 87,
                  "%s accrued_penalty.decided_by_ruling (CF1, the rate)" % uid)
        ctx.equal(penalty.get("grace_decided_by_ruling"), 88,
                  "%s accrued_penalty.grace_decided_by_ruling (OD-31, the grace days)" % uid)
        ctx.require("pending_decision" not in penalty and "grace_pending_decision" not in penalty,
                    "%s accrued_penalty still serves a pending_decision key - CF1 and OD-31 are both "
                    "decided, so nothing here should still read as open" % uid)

    ctx.proves = ("payable-today leads all %d summaries and penalty stays accrued/billed/paid/waived "
                  "- never netted, and decided rather than indicative (ruling 87 the rate, ruling 88 "
                  "the grace)" % len(uids))
    ctx.note("first key total_arrears_payable_today on %d/%d contracts" % (len(uids), len(uids)))


@check(11, "penalty invoicing ships now that CF1 is decided, but stays draft-only",
       "ruling 87 decided CF1, so the once-refused penalty invoice now succeeds - but the "
       "endpoint is a flag-gated stub with no PEAK call; peak_write_mode staying LOCKED/"
       "DRAFT_ONLY (C3) is the general write path's standing guard, not proof about this "
       "endpoint")
def check_penalty_invoice_drafts_only(api, ctx):
    uid = any_contract_uid(api)
    response = api.post("/v1/contracts/%s/penalty-invoices" % uid, {"period": "2026-10"})
    ctx.status(response, 201, "ruling 87 decided CF1 (the rate); this call must no longer refuse")
    ctx.require(response.json().get("created") is True,
                "POST .../penalty-invoices answered 201 but did not report created=true: %s"
                % _show(response.json()))

    # raise_penalty_invoice (main.py) checks only the feature flag and returns created=true -
    # it never calls raise_document, so today it creates no PEAK document, draft or otherwise.
    # The read below is not evidence about this endpoint's own output; it is the general write
    # path's standing guard (proven end to end in check 28), read here only to confirm it holds.
    config = api.get("/v1/config").json().get("config") or {}
    write_mode = config.get("peak_write_mode") or {}
    ctx.equal(write_mode.get("value"), "DRAFT_ONLY", "config.peak_write_mode.value (C3)")
    ctx.equal(write_mode.get("state"), "LOCKED", "config.peak_write_mode.state (C3)")
    ctx.require(write_mode.get("editable") is False,
                "config.peak_write_mode.editable is %s - C3 locks it, so nobody may flip Debt "
                "from drafting into approving" % _show(write_mode.get("editable")))
    ctx.proves = ("CF1 decided (ruling 87): the penalty invoice that used to refuse with 422 now "
                  "answers 201 created=true - but this is a flag-gated stub that makes no PEAK "
                  "call, so it creates no document at all today; peak_write_mode staying LOCKED/"
                  "DRAFT_ONLY (C3) is the general write path's standing guard, not proof about "
                  "this endpoint")
    ctx.note("POST .../penalty-invoices -> 201 created=true; config.peak_write_mode = %s/%s, editable=%s"
             % (write_mode.get("value"), write_mode.get("state"), write_mode.get("editable")))


@check(12, "OD-02 stops allocation; the old payments webhook says where PEAK posts",
       "OD-02: the manual path refuses and writes nothing; /v1/webhooks/peak/payments is gone (410) "
       "and names PEAK's registered webhooks, which store every event")
def check_allocation_and_webhook(api, ctx):
    uid = any_contract_uid(api)

    manual = api.post("/v1/contracts/%s/transactions" % uid,
                      {"amount": "5000.00", "received_on": "2026-10-23", "method": "TRANSFER"})
    ctx.status(manual, 422, "guessing the component order changes which instalment escalates")
    # §5.6 of the API brief assigns DEBT-MNY-0423 to allocation_rule_pending;
    # 0422 was a transcription slip and is assigned to nothing.
    payload = ctx.problem(manual, "allocation_rule_pending", "DEBT-MNY-0423")
    extensions = payload["extensions"]
    ctx.equal(extensions.get("pending_decision"), "OD-02", "extensions.pending_decision")
    ctx.require(extensions.get("owner"),
                "the OD-02 refusal names no owner - extensions.owner is empty, so nobody is "
                "accountable for closing it")

    # Fix-all P10c: this path answered 202 recorded=true and kept nothing. It is gone,
    # and the 410 names the three webhooks PEAK is registered on (they store each event).
    webhook = api.post("/v1/webhooks/peak/payments",
                       {"contract_uid": uid, "amount": "5000.00", "received_on": "2026-10-23"})
    ctx.status(webhook, 410, "claiming recorded=true for a payment nothing stored is how money goes missing")
    gone = ctx.problem(webhook, "webhook_gone", "DEBT-INT-0410")
    ctx.equal(gone["extensions"].get("paths"),
              ["/v1/webhooks/peak/contact", "/v1/webhooks/peak/invoice", "/v1/webhooks/peak/receipt"],
              "extensions.paths")
    ctx.proves = ("OD-02 open (owner %s): the manual path refuses and writes nothing; the old payments "
                  "webhook no longer claims to record money and names PEAK's registered webhooks"
                  % extensions["owner"])
    ctx.note("manual 422 allocation_rule_pending, /v1/webhooks/peak/payments 410 webhook_gone")


# --- 13-14  the daily contact slot -----------------------------------------------------------

@check(13, "one counting contact per customer per day",
       "the Thai Debt Collection Act limit: the second counting contact the same day is refused")
def check_daily_contact_slot(api, ctx):
    customer = slot_customer(api)
    uid = customer["uid"]

    first = api.post("/v1/contacts", contact_body(uid, 9, "OUTBOUND", "ANS_DISCUSSED"))
    if first.status == 409:
        raise CheckFailed(
            "the slot for %s on the synthetic day %s was already spent before this run started. "
            "That day is derived from the clock; wait a few seconds and re-run, or restart the API."
            % (customer["customer_no"], SLOT_DAY))
    ctx.status(first, 201)
    opened = first.json()
    ctx.require(opened.get("counted") is True,
                "the first outbound answered call did not count: counted=%s" % _show(opened.get("counted")))
    ctx.require(opened.get("lock_consumed") is True,
                "the first contact counted but consumed no lock, so the day is still open")

    second = api.post("/v1/contacts", contact_body(uid, 15, "OUTBOUND", "ANS_DISCUSSED"))
    ctx.status(second, 409,
               "a second counting contact the same day is unlawful, not merely discouraged")
    payload = ctx.problem(second, "contact_locked", "DEBT-COL-0409")
    ctx.equal(payload["extensions"].get("lock_level"), "PERSON",
              "the lock level (it is keyed on the person, never on the contract)")
    ctx.require(payload["extensions"].get("blocked_by_lock_id") is not None,
                "the refusal must name the lock that blocked it, for the audit trail")
    ctx.proves = ("one counting contact per customer per day - the second is refused on a PERSON "
                  "lock covering all %d of that customer's contracts" % customer.get("contract_count", 1))
    ctx.note("slot day %s, customer %s, blocked by lock %s"
             % (SLOT_DAY, customer["customer_no"], payload["extensions"]["blocked_by_lock_id"]))


@check(14, "an inbound contact never consumes the slot",
       "no override, manager action or config edit can make an inbound call count")
def check_inbound_never_counts(api, ctx):
    customer = slot_customer(api)
    uid = customer["uid"]
    for attempt in range(3):
        response = api.post(
            "/v1/contacts", contact_body(uid, 11 + attempt, "INBOUND", "INBOUND_CALLED"))
        ctx.status(response, 201,
                   "an inbound call is always accepted - the customer rang us")
        body = response.json()
        ctx.require(body.get("counted") is False,
                    "inbound attempt %d reports counted=%s. Counting needs an OUTBOUND direction, "
                    "a counting channel and a counting result; inbound can never reach true by "
                    "any route." % (attempt + 1, _show(body.get("counted"))))
        ctx.require(body.get("lock_consumed") is False,
                    "inbound attempt %d consumed the daily lock" % (attempt + 1))
    ctx.proves = ("inbound accepted 3 times on a day whose slot is already spent, counted false "
                  "every time - the rule is a property of the channel, not of the result")


# --- 15-16  the board and the authority gap -----------------------------------------------------

@check(15, "a computed board column cannot be deleted",
       "the board rule can place a card in each of the four, so removing one would "
       "leave the rule naming a column that does not exist")
def check_delete_column(api, ctx):
    response = api.get("/v1/board/columns")
    columns = response.json().get("columns") or []
    ctx.require(columns, "the board has no columns to delete")
    column = columns[0]
    ctx.require(column.get("column_id"),
                "a column has no column_id - identity is the id, never the name")
    # `api.delete(path, body=None)` — the client's own signature (`e2e_check.py:140`),
    # not requests' `json=`.
    deleted = api.delete("/v1/board/columns/%s" % column["column_id"],
                         body={"destination_column_id": "col_01H90"})
    ctx.status(deleted, 422, "a computed column must refuse deletion, not strand its rule")
    ctx.require(deleted.json().get("code") == "board_column_derived",
                "the refusal must name itself, so the Owner learns why")


@check(16, "an approval path may not name a vacant role",
       "REQ-IAM-015: an escalation to a vacant post is an escalation to nobody, silently")
def check_authority_gap(api, ctx):
    action = "FLAG_NON_PERFORMING"

    blocked = api.post("/v1/config/approval-paths", {"role": "DEBT_MANAGER", "action": action})
    ctx.status(blocked, 422, "there is no Debt Manager in post")
    payload = ctx.problem(blocked, "authority_gap_blocks_approval", "DEBT-IAM-0422")
    # `detail` is outside the compatibility contract, so the vacant role is read from
    # extensions - the machine-readable place it is named.
    ctx.equal(payload["extensions"].get("vacant_role"), "DEBT_MANAGER",
              "extensions.vacant_role (the refusal must name which post is empty)")

    allowed = api.post("/v1/config/approval-paths", {"role": "OWNER", "action": action})
    ctx.status(allowed, 201, "the Owner absorbs the vacant role's routes")
    ctx.require(allowed.json().get("created") is True,
                "the OWNER path answered 201 but did not report created=true")
    ctx.proves = ("a path naming the vacant DEBT_MANAGER is refused; the same path routed to OWNER "
                  "is created - the authority gap is absorbed, not ignored")
    ctx.note("DEBT_MANAGER 422 authority_gap_blocks_approval, OWNER 201 created")


# --- 17-24  the 2026-08-30 rebuild: the journey rules --------------------------------------

@check(17, "the working list follows the four tiers",
       "R11 - PTP due today leads, then arrears descend; next_up names the guided queue's head")
def check_tier_order(api, ctx):
    response = api.get("/v1/working-list")
    ctx.status(response, 200)
    body = response.json()
    items = body["items"]
    ctx.require(items, "the working list is empty - there is nothing to order")
    ctx.equal(items[0]["priority_reason"], "PTP_DUE_TODAY",
              "the first item's priority_reason (tier 1 leads regardless of size)")
    rest = [float(i["aggregate_overdue"]) for i in items[1:]]
    ctx.require(rest == sorted(rest, reverse=True),
                "after tier 1, arrears must descend (tier 2)")
    ctx.require(body["meta"].get("next_up"), "meta.next_up is absent - the guided queue has no head")
    ctx.note("first=%s reasons=%s" % (items[0]["customer"]["customer_no"],
                                      body["meta"]["counts_by_reason"]))


@check(18, "every receivable routes on entity + company_id, and service never leaks into the lease",
       "deck v20.0 - CASH is EPC's, LEASE is SPV's, and the S09 customer's lease aggregate stays clean")
def check_entity_routing(api, ctx):
    items = api.get("/v1/working-list").json()["items"]
    for item in items:
        if item.get("entity"):
            ctx.require(item.get("company_id"),
                        "%s carries entity without company_id" % item["customer"]["customer_no"])
    showcase = [i for i in items if i.get("service_billing")
                and i["service_billing"]["status"] in ("BILLING",)]
    ctx.require(showcase, "no month-37 service account is on the list - S09 is invisible")
    lease_side = [i for i in showcase if i["entity"] == "SPV"]
    ctx.require(lease_side, "the S09 showcase customer should hold an SPV lease")
    ctx.equal(float(lease_side[0]["aggregate_overdue"]), 0.0,
              "the lease aggregate of the service-arrears customer (isolation rule)")
    ctx.note("showcase=%s service=%s" % (lease_side[0]["customer"]["customer_no"],
                                         lease_side[0]["service_billing"]["dunning_stage"]))


@check(19, "the ladder is shown, never automatic",
       "OD-04 - a rung skip is refused, and declaring NPL is refused to an OFFICER outright")
def check_ladder_manual(api, ctx):
    cases = api.get("/v1/cases").json()["cases"]
    notice = [c for c in cases if c["stage"] == "NOTICE_30"]
    ctx.require(notice, "no case stands at NOTICE_30 - the skip rule cannot be proven")
    skip = _as_officer(api).post("/v1/cases/%s:advance" % notice[0]["uid"],
                                 {"to_stage": "NPL_DECLARED_90", "role": "OFFICER"})
    ctx.status(skip, 422, "skipping rungs must be refused")
    ctx.problem(skip, "ladder_stage_skip")
    offered = [c for c in cases if c["stage"] == "RESTRUCTURE_OFFER_60"]
    if offered:
        declare = _as_officer(api).post("/v1/cases/%s:advance" % offered[0]["uid"],
                                        {"to_stage": "NPL_DECLARED_90", "role": "OFFICER"})
        ctx.status(declare, 422, "an OFFICER may not declare NPL")
        ctx.problem(declare, "authority_gap_blocks_approval")
    ctx.note("skip refused; declaration role-gated")


@check(20, "service billing obeys the prepaid window and the 25th-30th law",
       "deck S09 - month<=36 refuses, and outside the window the 23rd refuses billing entirely")
def check_billing_window(api, ctx):
    accounts = api.get("/v1/service-billing").json()["accounts"]
    billing = [a for a in accounts if a["status"] == "BILLING"]
    prepaid = [a for a in accounts if a["status"] == "PREPAID"]
    ctx.require(billing and prepaid, "the book needs one BILLING and one PREPAID account")
    windowed = api.post("/v1/contracts/%s/service-billing:bill" % billing[0]["contract_uid"], {})
    ctx.status(windowed, 422, "the business date is the 23rd, outside 25-30")
    ctx.problem(windowed, "billing_window_closed")
    early = api.post("/v1/contracts/%s/service-billing:bill" % prepaid[0]["contract_uid"], {})
    ctx.status(early, 422, "months 1-36 are prepaid - nobody is invoiced")
    ctx.problem(early, "service_before_month_37")
    ctx.note("bill on the 23rd refused; prepaid month refused")


@check(21, "the 120-day deed paid 100% and cancelled the service account",
       "deck S07 - the assignment's documents exist and the month-37 service died with the lease")
def check_deed_effects(api, ctx):
    docs = api.get("/v1/intercompany/docs").json()["documents"]
    kinds = {d["doc_type"] for d in docs}
    ctx.require({"ASSIGNMENT_DEED", "NPL_BUYBACK_PAYMENT"} <= kinds,
                "the deed and the buyback payment must both be in the register")
    buyback = next(d for d in docs if d["doc_type"] == "NPL_BUYBACK_PAYMENT")
    ctx.equal(buyback["from_entity"], "EPC", "the buyback is paid BY EPC")
    ctx.equal(buyback["to_entity"], "SPV", "the buyback is paid TO SPV")
    accounts = api.get("/v1/service-billing").json()["accounts"]
    cancelled = [a for a in accounts if a["status"] == "CANCELLED"]
    ctx.require(cancelled, "no service account was cancelled by the assignment")
    ctx.note("buyback EPC->SPV %s; %d service account(s) cancelled"
             % (buyback.get("amount"), len(cancelled)))


@check(22, "a repossession lot cannot be sold before Dan prices it",
       "deck S12 - the stock stays blocked, and only Dan's saved price unblocks it")
def check_lot_gates(api, ctx):
    lots = api.get("/v1/repossession-lots").json()["lots"]
    blocked = [l for l in lots if l["stock_blocked"]]
    ctx.require(blocked, "no blocked lot exists - the pricing gate cannot be proven")
    lot = blocked[0]
    sell = api.post("/v1/repossession-lots/%s:sell" % lot["uid"], {})
    ctx.status(sell, 422, "the stock is blocked until a price exists")
    ctx.problem(sell, "resale_price_unset")
    if lot["status"] == "GRADED":
        # Through the OFFICER session: with AUTH on, the middleware rewrites the role
        # from the session, so an owner session would be allowed to price.
        not_dan = _as_officer(api).post("/v1/repossession-lots/%s:price" % lot["uid"],
                                        {"by": "Nok", "resale_price": "50000"})
        # AUTHORISED TEST EDIT 31 (Arina, 2026-09-14): a role that may not price is refused 403. One line.
        ctx.status(not_dan, 403, "the resale price is Operations' manual call")
    ctx.note("lot %s blocked and unpriceable by anyone but Dan" % lot["lot_no"])


@check(23, "a broken promise routes to manager review",
       "flow part 3 - closing a PTP as BROKEN opens a review carrying the customer's evidence")
def check_broken_ptp_review(api, ctx):
    items = api.get("/v1/working-list").json()["items"]
    free = [i for i in items if not i["open_ptp"] and float(i["aggregate_overdue"]) > 0]
    ctx.require(free, "no customer is free to promise")
    customer_uid = free[0]["customer"]["uid"]
    made = api.post("/v1/ptps", {"customer_uid": customer_uid, "promised_amount": "1234.00",
                                 "promise_date": "2026-10-30", "by": "e2e-check"})
    ctx.status(made, 201)
    ptp_uid = made.json()["ptp"]["uid"]
    broken = api.post("/v1/ptps/%s:close" % ptp_uid, {"outcome": "BROKEN", "by": "e2e-check"})
    ctx.status(broken, 200)
    review_uid = broken.json().get("manager_review_uid")
    ctx.require(review_uid, "closing BROKEN must open a manager review")
    reviews = api.get("/v1/manager-review").json()["reviews"]
    row = next((r for r in reviews if r["uid"] == review_uid), None)
    ctx.require(row and row["reason"] == "BROKEN_PTP", "the review must carry reason BROKEN_PTP")
    ctx.note("ptp %s -> review %s" % (ptp_uid, review_uid))


@check(24, "a manual status override carries provenance and never a silent no-op",
       "R14 - 'source says X, adjusted to Y, by whom, why' - and adjusting to the same value refuses")
def check_override_provenance(api, ctx):
    orders = api.get("/v1/orders").json()["items"]
    ctx.require(orders, "no order exists to override")
    no = orders[0]["no"]
    unreasoned = api.post("/v1/orders/%d/status-override" % no, {"adjusted_value": "Declined"})
    ctx.status(unreasoned, 422, "an override without a reason is refused")
    made = api.post("/v1/orders/%d/status-override" % no,
                    {"adjusted_value": "Declined", "reason": "e2e-check proves R14", "by": "e2e-check"})
    ctx.status(made, 201)
    override = made.json()["override"]
    for field in ("source_value", "adjusted_value", "by", "reason", "on"):
        ctx.require(override.get(field) is not None, "override is missing %s" % field)
    same = api.post("/v1/orders/%d/status-override" % no,
                    {"adjusted_value": override["source_value"], "reason": "noop", "by": "e2e-check"})
    ctx.status(same, 422, "adjusting to the source value changes nothing and refuses")
    ctx.problem(same, "override_source_unchanged")
    ctx.note("order %d: %s -> Declined by e2e-check" % (no, override["source_value"]))



# --- 2026-09-02 realignment (Requirements Amendment v2.6; Test Cases SCN v1.1) -------------

def _as_officer(api):
    """The client whose SESSION can prove a role refusal.

    With AUTH_MODE=on the login middleware rewrites X-Volt-Role from the session, so
    a header cannot make a MANAGER session an OFFICER — the refusal only exists for a
    client actually signed in as the officer account (2026-09-21: staging's smoke run
    turned the two "expected 403" checks into silent 200s, one of which PAUSED the
    real refetch). Local runs have login off and fall back to the same client.
    """
    return getattr(api, "officer", api) or api


def _enable_stub(api):
    """The PEAK stub is an Owner's switch (round-1 UAT finding); send the role.

    Ruling 46b: this used to build a raw urllib.request.Request, bypassing
    api.call() entirely -- so it carried none of api.cookie, the volt_session
    cookie this client deliberately keeps "like the one browser it stands in for"
    (api.call's own comment, above). It armed the stub in a session nobody read.
    That was invisible before ruling 43 / R4-F05, when peak_documents.py's
    transport override was process-wide (any session saw it); after R4-F05 made
    it per-session, the check the stub sets up read the real (armed) session
    while this call's own session-less request armed a phantom one -- the bug had
    been masking a harness defect the whole time. Routed through api.call so it
    joins the session the rest of the check already holds."""
    response = api.call("POST", "/v1/peak-documents/stub", {"enabled": True},
                         extra_headers={"X-Volt-Role": "OWNER"})
    if response.status != 200:
        raise CheckFailed("POST /v1/peak-documents/stub answered %d, expected 200" % response.status)
    return response.status

@check(25, "no contact closes without a next action",
       "REQ-COL-070 - the contact route refuses without next_action unless a PTP or an issue is created")
def check_next_action_required(api, ctx):
    today = api.get("/v1/today")
    ctx.status(today, 200)
    items = today.json()["items"]
    ctx.require(items, "Today is empty")
    for item in items:
        ctx.require(item["case"]["next_action"] and item["case"]["next_action_on"],
                    "%s is on Today without a next action" % item["customer"]["customer_no"])
    target = next(i for i in items if i["case"]["open_ptp"] is None)
    uid = target["customer"]["uid"]
    bare = api.post("/v1/cases/by-customer/%s/contacts" % uid,
                    {"result": "REACHED_ANSWERED", "counted": True, "by": "e2e-check"})
    ctx.status(bare, 422, "a contact with nothing after it is refused")
    ctx.problem(bare, "next_action_required")
    ctx.require(bare.json().get("message_th"), "the refusal carries a Thai message")
    with_next = api.post("/v1/cases/by-customer/%s/contacts" % uid,
                         {"result": "CALLBACK_REQUESTED", "counted": False, "by": "e2e-check",
                          "next_action": "CALLBACK", "next_action_on": today.json()["run"]["business_date"]})
    ctx.status(with_next, 201)
    ctx.equal(with_next.json()["case"]["next_action"], "CALLBACK", "the case's next action after the contact")
    ctx.note("customer %s: bare contact refused, callback accepted" % target["customer"]["customer_no"])


@check(26, "Today orders by the seven tiers and its counts reconcile",
       "REQ-COL-071 - tier ranks never decrease down the list and counts_by_tier sums to the total")
def check_today_tiers(api, ctx):
    body = api.get("/v1/today").json()
    items = body["items"]
    ranks = [i["tier_rank"] for i in items]
    ctx.require(ranks == sorted(ranks), "tier ranks are not monotonic")
    counts = body["meta"]["counts_by_tier"]
    ctx.equal(sum(counts.values()), len(items), "counts_by_tier total")
    for i in items:
        ctx.equal(i["priority_reason"], i["tier"], "priority_reason names the tier")
        ctx.require("band_set_code" in i and "aging_bucket" in i, "band pair missing on a Today item")
    ctx.note("counts=%s" % counts)


@check(27, "a gate enforced by a request is not a gate",
       "REQ-INV-002 - release refuses while any of the three Final v2 conditions is open, and the "
       "refusal names them; the down-payment gate and contract-signed evidence each need evidence")
def check_pipeline_gates(api, ctx):
    _enable_stub(api)
    items = api.get("/v1/pipeline?all=true").json()["items"]
    item = next((i for i in items if i["entity"] and i["amount_due"] and not i["released_at"]), None)
    ctx.require(item, "no releasable pipeline item with an entity and an amount")
    # Delta-100 D2h: release gates on the three served conditions. The served
    # `conditions` list is the oracle - entity_resolved passes from the entity pair,
    # contract_signed only ever from attached evidence, down_payment from its gate.
    keys = sorted(c["key"] for c in item.get("conditions") or [])
    ctx.equal(keys, ["contract_signed", "down_payment", "entity_resolved"],
              "the release conditions are the Final v2 three")
    open_conditions = sorted(c["key"] for c in item["conditions"] if not c.get("passed"))
    ctx.require(open_conditions, "the chosen item has no open condition - the refusal rule cannot be proven")
    ctx.require("contract_signed" in open_conditions and "down_payment" in open_conditions,
                "the chosen item should hold contract_signed and down_payment open; a seed that "
                "pre-passes them leaves this rule untested - restore the fixture rather than "
                "deleting the check")
    refused = api.post("/v1/pipeline/%s:release" % item["uid"], {"by": "e2e-check"})
    ctx.status(refused, 422, "release while a release condition is open")
    ctx.problem(refused, "gate_not_passed")
    ctx.equal(sorted(refused.json()["extensions"]["gates"]), open_conditions, "the open conditions are named")
    no_slip = api.post("/v1/pipeline/%s/gates/down-payment" % item["uid"], {"by": "e2e-check"})
    ctx.status(no_slip, 422, "the down-payment gate without a receipt or slip reference")
    ctx.problem(no_slip, "gate_evidence_required")
    no_note = api.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % item["uid"], {"by": "e2e-check"})
    ctx.status(no_note, 422, "contract-signed evidence must carry a note or a stored file")
    ctx.problem(no_note, "gate_evidence_required")
    ctx.note("item %s (%s): open %s" % (item["uid"], item["display_name"], ", ".join(open_conditions)))


@check(28, "Debt creates drafts and never approves",
       "C3 / REQ-ACC-031 - a release lands as DRAFT_CREATED with no QR; no route approves a document")
def check_draft_only(api, ctx):
    _enable_stub(api)
    items = api.get("/v1/pipeline?all=true").json()["items"]
    item = next((i for i in items if i["entity"] and i["amount_due"] and not i["released_at"]), None)
    ctx.require(item, "no releasable pipeline item")
    bd = api.get("/v1/today").json()["run"]["business_date"]
    # Final v2: contract_signed passes ONLY through attached evidence, and
    # down_payment through its gate (a slip already serving as the receipt).
    ctx.status(api.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % item["uid"],
                        {"note": "e2e-check contract signed", "by": "e2e-check"}), 201)
    ctx.status(api.post("/v1/pipeline/%s/gates/down-payment" % item["uid"], {"slip_ref": "e2e-slip", "by": "e2e-check"}), 200)
    # The EPC date is recorded for the after-release card; it no longer gates release.
    ctx.status(api.post("/v1/pipeline/%s/gates/epc-confirmed" % item["uid"], {"confirmed_on": bd, "source": "ODOO"}), 200)
    released = api.post("/v1/pipeline/%s:release" % item["uid"], {"by": "e2e-check"})
    ctx.status(released, 201)
    doc = released.json()["peak_document"]
    ctx.equal(doc["state"], "DRAFT_CREATED", "the document state after release")
    ctx.require(doc["idempotency_key"].startswith("debt-"), "the idempotency key is on the record")
    ctx.require(released.json()["invoice"]["qr_payload"] is None, "a draft carries no QR (PC3)")
    not_yet = api.post("/v1/pipeline/%s/delivery" % item["uid"], {"channel": "LINE", "by": "e2e-check"})
    ctx.status(not_yet, 422, "delivery before approval")
    ctx.problem(not_yet, "invoice_not_approved")
    approve = api.post("/v1/peak-documents/%s:approve" % doc["uid"], {})
    ctx.require(approve.status in (404, 405), "an approve route exists (%d) - Debt must never approve" % approve.status)
    refreshed = api.post("/v1/peak-documents/%s:refresh" % doc["uid"], {}).json()["document"]
    ctx.equal(refreshed["state"], "APPROVED_IN_PEAK", "state read back from the (stub) PEAK")
    ctx.require(refreshed["qr_payload"], "the QR arrives only with approval")
    ctx.note("%s -> %s (%s)" % (doc["uid"], refreshed["state"], refreshed["peak_number"]))


@check(29, "the migration report is honest about the export",
       "REQ-INT-032 - counts reconcile against the sheet's own pivots or say why not; the gap list has an owner")
def check_migration_honesty(api, ctx):
    report = api.get("/v1/migration/report")
    ctx.status(report, 200)
    body = report.json()
    serving = (body.get("source_chain") or {}).get("serving_code")
    if serving == "ODOO":
        # The served book is crm.lead: identities with no contracts, so the engine
        # book is legitimately 0 and there is no SHEET run to reconcile — None is the
        # honest answer, not a made-up boolean (the report says why, row by row).
        ctx.note("serving_code=ODOO - engine_book 0 and reconciled None are by design here")
        ctx.require(body["counts"]["registry"] > 1,
                    "the served registry is thin: %d" % body["counts"]["registry"])
        ctx.require(body["run"].get("reconciled") is None,
                    "no sheet run is being served, so reconciled must read None")
    else:
        ctx.require(body["counts"]["engine_book"] > 100,
                    "the migrated book is thin: %d" % body["counts"]["engine_book"])
        ctx.require(isinstance(body["run"]["reconciled"], bool), "reconciled must be stated")
    for row in body["reconciliation"]:
        if not row["matches"]:
            ctx.require(row["note"], "%s does not reconcile and no reason is given" % row["payment_status"])
    gap = api.get("/v1/migration/gap-list").json()
    ctx.equal(gap["meta"]["owner"], "Operations (Dan)", "the gap list names its owner")
    ctx.note("engine_book=%d registry=%d reconciled=%s gap=%d" % (
        body["counts"]["engine_book"], body["counts"]["registry"], body["run"]["reconciled"], gap["meta"]["total"]))


@check(30, "the crm.lead pipeline reads Odoo only: a file is pointed at the sheet import",
       "fix-all 2026-09-25 - the crm.lead file door is closed; the New Order Master lands through POST /v1/imports, and a pull may add identities but never a balance")
def check_pipeline_lands_identity_only(api, ctx):
    before = api.get("/v1/migration/report").json()["counts"]
    raw = ("Volt ID,Phone,Order Status\r\n"
           "VL9999001,0912345678,Order - Done\r\n").encode("utf-8-sig")
    run = api.call("POST", "/v1/pipelines/crm-lead:run", raw_body=raw,
                   extra_headers={"X-Volt-Role": "MANAGER",
                                  "X-Volt-Filename": "x.csv",
                                  "content-type": "text/csv"})
    ctx.status(run, 422)
    ctx.equal(run.json()["code"], "use_sheet_upload", "a file is refused by name")
    ctx.equal(run.json()["extensions"]["use"], "/v1/imports", "and pointed at the sheet import")

    refused = _as_officer(api).post("/v1/pipelines/crm-lead:run", {"source": "odoo"},
                                    extra_headers={"X-Volt-Role": "OFFICER"})
    ctx.status(refused, 403)

    after = api.get("/v1/migration/report").json()["counts"]
    ctx.equal(after["engine_book"], before["engine_book"],
              "an identity with no money must not enter the engine book")
    ctx.note("file refused 422 use_sheet_upload; engine_book unchanged at %d" % after["engine_book"])

@check(31, "a started run can be watched, and the refetch is on by itself",
       "2026-09-21 - progress is reported by the work itself, the 15-minute refetch is on from boot, and pausing is a Manager's act")
def check_run_is_watchable(api, ctx):
    schedule = api.get("/v1/pipelines/crm-lead/schedule")
    ctx.status(schedule, 200)
    if not schedule.json()["enabled"]:
        # A person (or an older smoke run) paused it. The check asserts the DEFAULT, so
        # it restores the estate first — a Manager's own act, and the reason check 31
        # used to LEAVE staging paused: the refusal below became a real PUT once a
        # session was signed in.
        api.call("PUT", "/v1/pipelines/crm-lead/schedule", {"enabled": True, "interval_minutes": 15},
                 extra_headers={"X-Volt-Role": "MANAGER"})
        schedule = api.get("/v1/pipelines/crm-lead/schedule")
    ctx.equal(schedule.json()["enabled"], True, "the refetch is on from boot (2026-09-21 ruling)")
    ctx.equal(schedule.json()["auto"], True, "and it says the state is the process default")
    ctx.equal(schedule.json()["in_process_only"], True,
              "the timer must say it dies with the process")
    ctx.require("odoo_configured" in schedule.json(),
                "the screen needs to know whether a fetch is possible at all")

    refused = _as_officer(api).call("PUT", "/v1/pipelines/crm-lead/schedule", {"enabled": False},
                                     extra_headers={"X-Volt-Role": "OFFICER"})
    ctx.status(refused, 403)

    # The Odoo door (the file door closed 2026-09-25). Without Odoo credentials the
    # run fails by name; with them it is one more NEW_ONLY pull, which lands only
    # what changed.
    started = api.post("/v1/pipelines/crm-lead:start", {"source": "odoo"},
                       extra_headers={"X-Volt-Role": "MANAGER"})
    ctx.status(started, 202)
    uid = started.json()["uid"]
    run = started.json()
    for _ in range(40):
        run = api.get("/v1/pipelines/crm-lead/runs/%s" % uid).json()
        if run["state"] != "running":
            break
        time.sleep(0.25)
    if run["state"] == "running" and schedule.json()["odoo_configured"]:
        # A real 34k-lead pull takes about a minute and a half: watchable, not awaited.
        ctx.require(run.get("read") is not None, "a running pull reports what it has read")
    else:
        ctx.require(run["state"] in ("done", "failed"),
                    "the run must reach an end state, not stay running for ever")
    if run["state"] == "failed":
        ctx.require((run.get("problem") or {}).get("code"),
                    "a failed run must say why, by code")
    ctx.require(run["elapsed_seconds"] >= 0, "a run must report how long it took")
    ctx.note("run %s -> %s in %.2fs" % (uid, run["state"], run["elapsed_seconds"]))

# --- running and reporting -----------------------------------------------------------------

GREEN = "\033[32m"
RED = "\033[31;1m"
DIM = "\033[2m"
OFF = "\033[0m"


def run_checks(api):
    results = []
    for spec in sorted(CHECKS, key=lambda s: s.number):
        ctx = Ctx(spec)
        started = time.time()
        try:
            spec.fn(api, ctx)
            status, error = "PASS", None
        except CheckFailed as exc:
            status, error = "FAIL", str(exc)
        except Unreachable:
            raise
        except Exception as exc:  # a malformed payload must fail the check, not the run
            status, error = "FAIL", "%s: %s" % (type(exc).__name__, exc)
        results.append({
            "number": spec.number,
            "name": spec.name,
            "proves": ctx.proves,
            "status": status,
            "evidence": [e for e in ctx.evidence if e],
            "error": error,
            "duration_ms": int((time.time() - started) * 1000),
        })
    return results


def report_human(results, base_url, colour):
    def paint(text, code):
        return code + text + OFF if colour else text

    print("Volt Debt prototype - black-box end-to-end check")
    print("  base url  %s" % base_url)
    print("  slot day  %s   (checks 13-14 use a synthetic day so the run repeats cleanly)" % SLOT_DAY)
    print("")
    for result in results:
        mark = paint("PASS", GREEN) if result["status"] == "PASS" else paint("FAIL", RED)
        print("%3d  %s  %s" % (result["number"], mark, result["name"]))
        print("     %s" % paint("proves: " + result["proves"], DIM))
        for line in result["evidence"]:
            print("     %s" % paint("        " + line, DIM))
        if result["error"]:
            print("     %s" % paint("BROKEN: " + result["error"], RED))
        print("")

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = len(results) - passed
    verdict = paint("ALL CHECKS PASSED", GREEN) if not failed else paint("%d CHECK(S) FAILED" % failed, RED)
    print("%d checks, %d passed, %d failed   %s" % (len(results), passed, failed, verdict))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Black-box end-to-end check for the Volt Debt prototype API.",
        epilog="Exit codes: 0 all passed, 1 a check failed, 2 the API is not answering.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000",
                        help="where the API is already running (default: %(default)s)")
    parser.add_argument("--json", action="store_true",
                        help="emit machine-readable results and nothing else")
    parser.add_argument("--timeout", type=float, default=10.0,
                        help="per-request timeout in seconds (default: %(default)s)")
    parser.add_argument("--username", default=os.environ.get("VOLT_USER"),
                        help="test account to sign in with on a deployed estate (AUTH_MODE=on)")
    parser.add_argument("--password", default=os.environ.get("VOLT_PASS"),
                        help="that account's password (prefer VOLT_PASS over argv)")
    parser.add_argument("--officer-username", default=os.environ.get("VOLT_OFFICER_USER"),
                        help="the account whose SESSION proves role refusals (default: officer)")
    parser.add_argument("--officer-password", default=os.environ.get("VOLT_OFFICER_PASS"),
                        help="that account's password (default: --password)")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    api = Api(args.base_url, args.timeout)

    # This script starts nothing. Say so plainly rather than failing 16 times.
    try:
        api.get("/livez")
    except Unreachable as exc:
        message = [
            "The API at %s is not answering." % api.base,
            "  %s" % exc,
            "",
            "This script starts nothing. Start the API first:",
            "  cd %s/backend && .venv/bin/uvicorn app.main:app --port 8000" % REPO_ROOT,
            "",
            "Or start the API, the vite dev server and this check together:",
            "  %s/scripts/run_prototype.sh" % REPO_ROOT,
        ]
        if args.json:
            print(json.dumps({"base_url": api.base, "ok": False, "unreachable": str(exc),
                              "checks": []}, indent=2))
        else:
            sys.stderr.write("\n".join(message) + "\n")
        return 2

    # A deployed estate runs AUTH_MODE=on; sign in before any check or every one of
    # them reads the login page's refusal instead of the product.
    if args.username:
        if not args.password:
            sys.stderr.write("--username needs --password (or VOLT_PASS)\n")
            return 2
        if not api.login(args.username, args.password):
            sys.stderr.write("Could not sign in as %s: the API refused it. Wrong password,\n"
                             "a locked account, or login is off at %s.\n" % (args.username, api.base))
            return 2
        # The role-refusal checks need a SESSION whose role is OFFICER (the middleware
        # rewrites the header). Sign the second account in when it works; say so, and
        # fall back to the main client when it does not.
        officer_user = args.officer_username or "officer"
        officer_pass = args.officer_password or args.password
        officer_api = Api(args.base_url, args.timeout)
        if officer_api.login(officer_user, officer_pass):
            api.officer = officer_api
            sys.stderr.write("signed in: %s, officer client: %s\n" % (args.username, officer_user))
        else:
            sys.stderr.write("note: could not sign in as %s — role-refusal checks run as %s\n"
                             % (officer_user, args.username))

    try:
        results = run_checks(api)
    except Unreachable as exc:
        sys.stderr.write("The API stopped answering during the run: %s\n" % exc)
        return 2

    failed = sum(1 for r in results if r["status"] != "PASS")
    if args.json:
        print(json.dumps({
            "base_url": api.base,
            "slot_day": str(SLOT_DAY),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "total": len(results),
            "passed": len(results) - failed,
            "failed": failed,
            "ok": failed == 0,
            "checks": results,
        }, indent=2, ensure_ascii=False))
    else:
        report_human(results, api.base, colour=sys.stdout.isatty())
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
