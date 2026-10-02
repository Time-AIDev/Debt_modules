"""Feedback Round 1, WP7 / B2 — Today's filter bar is served, and it refuses what it
does not know.

The tier strip and the "whole team today" panel became one filter bar (design WP7).
Every number the bar shows is the server's: `meta.tier_counts` (the tier options'
counts, under every filter except the tier filter) and `meta.officer_totals` (each
officer's whole list today — the numbers the old panel fetched with one /v1/today
call per officer). Every value the bar can send is validated; an unknown one is a
422 carrying the known list, never a silently empty or silently unfiltered desk.

Every test here is an ADDITION.
"""
import pytest
from fastapi.testclient import TestClient

from app import officers
from app import today as today_domain
from app.main import app


def _thai(text):
    return any("฀" <= ch <= "๿" for ch in (text or ""))


@pytest.fixture
def client():
    return TestClient(app)


def _today(client, **params):
    response = client.get("/v1/today", params=params)
    assert response.status_code == 200, response.json()
    return response.json()


@pytest.mark.parametrize("field,value", [
    ("tier", "ALMOST_ROUTINE"),
    ("payment_status", "PAID"),
    ("dc_status", "BANANA"),
    ("product", "LOAN"),
    ("officer", "nobody-at-all"),
])
def test_an_unknown_filter_value_is_refused_with_the_known_list(client, field, value):
    response = client.get("/v1/today", params={field: value})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "validation_failed"
    error = body["errors"][0]
    assert error["pointer"] == "/" + field
    assert error["code"] == "value_unknown"
    assert error["known"] and value not in error["known"]
    assert _thai(error["message_th"])


def test_an_empty_filter_is_no_filter(client):
    everyone = _today(client)
    blank = _today(client, tier="", payment_status="", dc_status="", product="", q="", officer="")
    assert blank["meta"]["total"] == everyone["meta"]["total"]
    assert blank["meta"]["filters"] == {"officer": None, "tier": None, "payment_status": None,
                                        "dc_status": None, "product": None, "q": None}


def test_the_tier_filter_narrows_the_desk_and_its_options_keep_every_tiers_count(client):
    everyone = _today(client)
    counts = everyone["meta"]["tier_counts"]
    assert set(counts) == set(today_domain.TIERS)
    # With no tier filter the options' counts ARE the partition the chips used to draw.
    assert counts == everyone["meta"]["counts_by_tier"]
    tier = next(t for t in today_domain.TIERS if 0 < counts[t] < everyone["meta"]["total"])
    only = _today(client, tier=tier)
    assert only["meta"]["total"] == counts[tier] == len(only["items"])
    assert {i["tier"] for i in only["items"]} == {tier}
    assert sum(only["meta"]["counts_by_tier"].values()) == only["meta"]["total"]
    assert only["meta"]["next_up"] in {i["customer"]["uid"] for i in only["items"]} | {None}
    # The options still say what every OTHER tier would show — the filter bar never
    # tells an officer that the tier they are not looking at is empty.
    assert only["meta"]["tier_counts"] == counts
    assert only["meta"]["filters"]["tier"] == tier


def test_payment_status_dc_status_and_product_narrow_the_desk_the_work_book_way(client):
    everyone = _today(client)["items"]
    late = _today(client, payment_status="LATE")
    assert late["meta"]["total"] == sum(1 for i in everyone if i["case"]["payment_status"] == "LATE") > 0
    assert all(i["case"]["payment_status"] == "LATE" for i in late["items"])

    code = next(i["case"]["dc_status"] for i in everyone if i["case"]["dc_status"])
    narrowed = _today(client, dc_status=code)
    assert narrowed["meta"]["total"] == sum(1 for i in everyone if i["case"]["dc_status"] == code)

    for product in today_domain.PRODUCTS:
        expected = [i for i in everyone
                    if i["case"]["sheet"] and ("LEASE" if i["entity"] == "SPV" else "CASH") == product]
        assert _today(client, product=product)["meta"]["total"] == len(expected)
    # The Work Book applies the same rule and also serves CLOSED rows; its open rows agree.
    book = client.get("/v1/workbook", params={"product": "LEASE"}).json()["rows"]
    assert len([r for r in book if r["case"]["payment_status"] not in ("CLOSED", "TERMINATED")]) == \
        _today(client, product="LEASE")["meta"]["total"]


def test_the_search_box_matches_name_volt_id_and_customer_no(client):
    row = _today(client)["items"][0]
    for needle in (row["customer"]["display_name"][:4], row["case"]["volt_id"], row["customer"]["customer_no"]):
        if not needle:
            continue
        hits = _today(client, q=needle.upper())["items"]
        assert row["customer"]["uid"] in {i["customer"]["uid"] for i in hits}, needle
    assert _today(client, q="zz-no-such-customer-zz")["meta"]["total"] == 0


def test_officer_totals_are_each_officers_own_list_and_name_the_whole_team(client):
    meta = _today(client)["meta"]
    totals = meta["officer_totals"]
    assert {row["uid"] for row in officers.registry()} <= set(totals)
    for uid, n in totals.items():
        assert _today(client, officer=uid)["meta"]["total"] == n, uid
    # They are desk sizes, not a facet: another filter never moves them.
    assert _today(client, payment_status="NPL")["meta"]["officer_totals"] == totals
    assert _thai(meta["officer_totals_note_th"])


def test_an_officer_a_lead_assigned_work_to_is_a_filter_the_desk_accepts(client):
    uid = _today(client)["items"][0]["customer"]["uid"]
    assigned = client.post("/v1/customers/%s/assign" % uid, headers={"X-Volt-Role": "MANAGER"},
                           json={"officer_uid": "newhire"})
    assert assigned.status_code == 200
    body = _today(client, officer="newhire")
    assert [i["customer"]["uid"] for i in body["items"]] == [uid]
    assert body["meta"]["officer_totals"]["newhire"] == 1


def test_the_acting_officers_own_empty_desk_is_never_a_refusal(client):
    body = client.get("/v1/today", params={"officer": "newhire"}, headers={"X-Volt-Officer": "newhire"})
    assert body.status_code == 200
    assert body.json()["meta"]["total"] == 0 and body.json()["items"] == []
    # Someone else's unknown name is still refused.
    assert client.get("/v1/today", params={"officer": "newhire"}, headers={"X-Volt-Officer": "nantapol"}).status_code == 422


def test_the_filters_combine_and_the_ladder_filter_is_still_refused_first(client):
    both = _today(client, officer="thip", payment_status="LATE")
    assert all(i["case"]["officer_uid"] == "thip" and i["case"]["payment_status"] == "LATE" for i in both["items"])
    refused = client.get("/v1/today", params={"ladder_indicative": "ALMOST_NPL", "tier": "NOPE"})
    assert refused.status_code == 422
    assert refused.json()["errors"][0]["pointer"] == "/ladder_indicative"


# --- feedback round 2, TASK-108: the unassigned desk (ADDITIONS ONLY) ---------------

def test_the_unassigned_desk_lists_only_rows_with_no_officer(client):
    from app import cases as cases_domain
    from app import journey
    client.cookies.set("volt_session", "shared")
    cs = cases_domain.for_current()
    uid = _today(client)["items"][0]["customer"]["uid"]
    journey.for_current().officer_overlay.pop(uid, None)
    cs.cases[uid]["officer_uid"] = None
    body = _today(client, unassigned=1)
    assert [i["customer"]["uid"] for i in body["items"]] == [uid]
    assert body["meta"]["unassigned_total"] == 1
    assert all(not i["case"]["officer_uid"] for i in body["items"])


def test_officer_and_unassigned_together_are_refused(client):
    refused = client.get("/v1/today", params={"officer": "nantapol", "unassigned": 1})
    assert refused.status_code == 422
    assert refused.json()["errors"][0]["pointer"] == "/unassigned"
