"""The endpoint refuses what it should and reports what it did."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_an_officer_may_not_run_the_pipeline():
    r = client.post("/v1/pipelines/crm-lead:run", json={"source": "odoo"},
                    headers={"X-Volt-Role": "OFFICER"})
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"
    assert r.json()["message_th"]


def test_an_unknown_source_is_a_validation_problem_not_a_500():
    r = client.post("/v1/pipelines/crm-lead:run", json={"source": "telepathy"},
                    headers={"X-Volt-Role": "MANAGER"})
    assert r.status_code == 422
    assert r.json()["errors"][0]["pointer"] == "/source"


def test_a_file_is_pointed_at_the_sheet_import_by_both_doors():
    """2026-09-25: the crm.lead file door is closed — it read the sheet with Odoo's
    mapping (Watt x1000, money dropped) and landed it as ODOO. The New Order Master
    lands through POST /v1/imports."""
    raw = ("Volt ID,Phone,Order Status\r\n"
           "VL0000143,0925423597,Order - Done\r\n").encode("utf-8-sig")
    for door in (":run", ":start"):
        r = client.post("/v1/pipelines/crm-lead" + door, content=raw,
                        headers={"X-Volt-Role": "MANAGER", "X-Volt-Filename": "x.csv",
                                 "Content-Type": "text/csv"})
        assert r.status_code == 422, door
        assert r.json()["code"] == "use_sheet_upload"
        assert r.json()["extensions"]["use"] == "/v1/imports"
        assert r.json()["message_th"]


def test_starting_a_run_answers_at_once_with_a_uid_to_watch():
    r = client.post("/v1/pipelines/crm-lead:start", json={"source": "odoo"},
                    headers={"X-Volt-Role": "MANAGER"})
    assert r.status_code == 202
    body = r.json()
    assert body["uid"].startswith("run-")
    assert body["state"] in ("queued", "uploading", "parsing", "applying", "done", "failed")


def test_an_officer_may_not_start_a_run():
    r = client.post("/v1/pipelines/crm-lead:start", json={"source": "odoo"},
                    headers={"X-Volt-Role": "OFFICER"})
    assert r.status_code == 403


def test_an_unknown_run_is_a_404_not_an_invented_one():
    r = client.get("/v1/pipelines/crm-lead/runs/run-nope")
    assert r.status_code == 404


def test_the_schedule_runs_by_default_and_a_manager_can_still_pause_it():
    """2026-09-21: on from boot — the Import data screen defaults to the Odoo tab and
    says the system fetches by itself. `disable` remains an ops escape hatch (and the
    next boot turns it back on via `ensure_auto`)."""
    body = client.get("/v1/pipelines/crm-lead/schedule").json()
    assert body["enabled"] is True
    assert body["auto"] is True
    assert body["in_process_only"] is True
    # The OFFICER gate is unchanged.
    refused = client.put("/v1/pipelines/crm-lead/schedule",
                         json={"enabled": False}, headers={"X-Volt-Role": "OFFICER"})
    assert refused.status_code == 403
    off = client.put("/v1/pipelines/crm-lead/schedule", json={"enabled": False},
                     headers={"X-Volt-Role": "MANAGER"})
    assert off.status_code == 200
    assert off.json()["enabled"] is False
    on = client.put("/v1/pipelines/crm-lead/schedule",
                    json={"enabled": True, "interval_minutes": 15},
                    headers={"X-Volt-Role": "MANAGER"})
    assert on.status_code == 200
    assert on.json()["enabled"] is True
    assert on.json()["interval_minutes"] == 15


def test_the_default_mode_is_new_only_and_an_unknown_mode_is_refused():
    r = client.post("/v1/pipelines/crm-lead:start", json={"source": "odoo"},
                    headers={"X-Volt-Role": "MANAGER"})
    assert r.status_code == 202 and r.json()["mode"] == "NEW_ONLY"
    r = client.post("/v1/pipelines/crm-lead:start",
                    json={"source": "odoo", "mode": "SOMETHING"},
                    headers={"X-Volt-Role": "MANAGER"})
    assert r.status_code == 422 and r.json()["errors"][0]["pointer"] == "/mode"


def test_eligibility_preview_and_apply_are_manager_only_and_use_a_one_time_token(monkeypatch):
    from app.pipelines import service

    expected = {"eligible_source": 360, "normalised": 360,
                "would_retire": 12, "eligibility_exclusions": {"not_won": 35800}}
    monkeypatch.setattr(service, "preview_eligibility",
                        lambda principal: {"token": "elig-test", "expected": expected,
                                           "expires_in_hours": 24})
    monkeypatch.setattr(service, "apply_eligibility",
                        lambda token, principal: {"uid": "run-test", "state": "done",
                                                  "run_id": 7, "retired": 12})
    assert client.post("/v1/pipelines/crm-lead/eligibility:preview",
                       headers={"X-Volt-Role": "OFFICER"}).status_code == 403
    preview = client.post("/v1/pipelines/crm-lead/eligibility:preview",
                          headers={"X-Volt-Role": "MANAGER"})
    assert preview.status_code == 200 and preview.json()["token"] == "elig-test"
    missing = client.post("/v1/pipelines/crm-lead/eligibility:apply", json={},
                          headers={"X-Volt-Role": "MANAGER"})
    assert missing.status_code == 422
    applied = client.post("/v1/pipelines/crm-lead/eligibility:apply",
                          json={"token": "elig-test"}, headers={"X-Volt-Role": "MANAGER"})
    assert applied.status_code == 200 and applied.json()["retired"] == 12


# --- the pre-install queue's own age (prototype 2038) --------------------------------

def test_pipeline_rows_serve_waiting_days_and_the_case_dpd():
    """The list row's heat needs an age the row did not carry: `waiting_days` is the
    business date minus the planned install date, clipped at zero, and a row that
    already has a case also carries the same DPD /v1/today serves for it."""
    from datetime import date

    from app.config import settings
    body = client.get("/v1/pipeline", params={"all": "true"}).json()
    assert body["items"]
    today_dpd = {i["customer"]["uid"]: i["oldest_dpd"] for i in client.get("/v1/today").json()["items"]}
    for item in body["items"]:
        planned = item.get("planned_install_on")
        if not planned:
            assert item["waiting_days"] is None
        else:
            expected = max(0, (settings.business_date - date.fromisoformat(str(planned)[:10])).days)
            assert item["waiting_days"] == expected
        if item["has_case"]:
            assert "case_dpd" in item
            if item["customer_uid"] in today_dpd:
                assert item["case_dpd"] == today_dpd[item["customer_uid"]]
        else:
            assert item["case_dpd"] is None
    # A fresh seed plants plans on both sides of the business date, so the rows prove
    # both halves: a past plan waits, a future one is 0 — never a negative age.
    assert any(i["waiting_days"] and i["waiting_days"] > 0 for i in body["items"])
    assert any(i["waiting_days"] == 0 for i in body["items"])
    assert any(i["has_case"] and i["case_dpd"] is not None for i in body["items"])



# --- Delta-100 D2h — the three conditions, their evidence, and the row's money -------

def _thai(text):
    return any("฀" <= ch <= "๿" for ch in (text or ""))


def _unreleased_with_amount():
    rows = client.get("/v1/pipeline", params={"all": "true"}).json()["items"]
    return next(i for i in rows if not i["released_at"] and i["entity"] and i["amount_due"])


def test_the_row_serves_the_prototype_three_conditions_order_ref_and_risk():
    body = client.get("/v1/pipeline", params={"all": "true"}).json()
    assert body["items"]
    for item in body["items"]:
        conds = item["conditions"]
        assert [c["key"] for c in conds] == ["contract_signed", "down_payment", "entity_resolved"]
        for c in conds:
            assert c["state"] in ("OPEN", "PASSED") and c["passed"] == (c["state"] == "PASSED")
            assert _thai(c["label_th"]) and c["label_en"] and _thai(c["note_th"]) and c["note_en"]
            assert isinstance(c["evidence"], list) and c["evidence_count"] == len(c["evidence"])
            assert c["state_label_th"] and c["state_label_en"] and c["attach_label_th"] and c["attach_label_en"]
            assert c["evidence_scope"] == "pipeline:%s:condition:%s" % (item["uid"], c["key"])
        # Prototype 544: the row's reference. No SO- number exists upstream, so a row
        # with no Odoo link serves its internal uid AND says that is what it is; a row
        # whose order carries an odoo_id serves that, with no "internal" claim.
        if item["order_ref_source"] == "INTERNAL_UID":
            assert item["order_ref"] == item["uid"]
            assert item["order_ref_note_th"] and item["order_ref_note_en"]
        else:
            assert item["order_ref_source"] == "ODOO" and item["order_ref"]
            assert item["order_ref_note_th"] is None and item["order_ref_note_en"] is None
        # Delta-100 D2a: the same risk score the record serves, bounded 0..100.
        assert item["risk_score"] is None or 0 <= item["risk_score"] <= 100
        # The existing row keys are untouched.
        assert "waiting_days" in item and "case_dpd" in item


def test_contract_signed_passes_only_by_evidence_and_flips_back_on_removal():
    item = _unreleased_with_amount()
    uid = item["uid"]
    before = next(c for c in item["conditions"] if c["key"] == "contract_signed")
    assert before["state"] == "OPEN" and before["evidence"] == []

    made = client.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % uid,
                       json={"note": "สำเนาสัญญาที่ลงนามทั้งสองฝ่าย", "by": "thip"})
    assert made.status_code == 201, made.json()
    record = made.json()["evidence"]
    assert record["condition"] == "contract_signed" and record["note"].startswith("สำเนาสัญญา")
    assert record["file_uid"] is None and record["uploaded_by"] == "thip" and record["uploaded_at"]
    assert record["scope"] == "pipeline:%s:condition:contract_signed" % uid
    row = made.json()["item"]
    assert next(c for c in row["conditions"] if c["key"] == "contract_signed")["state"] == "PASSED"

    # A second record on the same condition keeps it passed, and removing ONE of two
    # does not flip it back — only removing the LAST does.
    second = client.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % uid,
                         json={"note": "ภาคผนวก", "by": "thip"})
    assert second.status_code == 201
    removed = client.post("/v1/pipeline/%s/conditions/contract_signed/evidence/%s:remove"
                          % (uid, record["uid"]), json={"by": "thip"})
    assert removed.status_code == 200, removed.json()
    row = removed.json()["item"]
    assert next(c for c in row["conditions"] if c["key"] == "contract_signed")["state"] == "PASSED"

    last = second.json()["evidence"]["uid"]
    emptied = client.post("/v1/pipeline/%s/conditions/contract_signed/evidence/%s:remove"
                          % (uid, last), json={"by": "thip"})
    assert emptied.status_code == 200
    assert next(c for c in emptied.json()["item"]["conditions"]
                if c["key"] == "contract_signed")["state"] == "OPEN"
    assert emptied.json()["item"]["conditions"][0]["evidence"] == []


def test_attaching_evidence_needs_a_note_or_a_stored_file():
    uid = _unreleased_with_amount()["uid"]
    r = client.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % uid, json={"by": "thip"})
    assert r.status_code == 422 and r.json()["code"] == "gate_evidence_required"
    assert r.json()["message_th"]


def test_an_unknown_condition_or_evidence_uid_is_refused_by_name():
    uid = _unreleased_with_amount()["uid"]
    bad = client.post("/v1/pipeline/%s/conditions/not_a_condition/evidence" % uid, json={"note": "x"})
    assert bad.status_code == 422 and bad.json()["code"] == "gate_key_unknown"
    missing = client.post("/v1/pipeline/%s/conditions/contract_signed/evidence/pev-99999:remove" % uid,
                          json={"by": "thip"})
    assert missing.status_code == 404 and missing.json()["code"] == "evidence_not_found"


def test_a_stored_file_rides_the_evidence_record_through_the_attachments_module():
    from tests.test_attachments_guard import _png
    uid = _unreleased_with_amount()["uid"]
    scope = "pipeline:%s:condition:contract_signed" % uid
    uploaded = client.post("/v1/attachments", content=_png(),
                           headers={"X-Volt-Role": "OFFICER", "X-Volt-Officer": "thip",
                                    "X-Volt-Filename": "contract.png",
                                    "Content-Type": "application/octet-stream"})
    assert uploaded.status_code == 201, uploaded.json()
    file_uid = uploaded.json()["attachment"]["uid"]

    made = client.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % uid,
                       json={"note": "ไฟล์สัญญา", "file_uid": file_uid, "by": "thip"})
    assert made.status_code == 201, made.json()
    assert made.json()["evidence"]["file_uid"] == file_uid

    listed = client.get("/v1/attachments", params={"attached_to": scope})
    assert [a["uid"] for a in listed.json()["attachments"]] == [file_uid]
    # The condition is passed by the file alone; removing the last evidence reopens it.
    assert next(c for c in made.json()["item"]["conditions"]
                if c["key"] == "contract_signed")["state"] == "PASSED"

    unknown = client.post("/v1/pipeline/%s/conditions/down_payment/evidence" % uid,
                          json={"note": "x", "file_uid": "att-doesnotexist"})
    assert unknown.status_code == 422 and unknown.json()["code"] == "attachment_unknown"


def test_release_gates_on_the_three_conditions_and_the_epc_date_still_travels():
    from app.config import settings
    item = _unreleased_with_amount()
    uid = item["uid"]
    assert client.post("/v1/pipeline/%s/gates/down-payment" % uid,
                       json={"slip_ref": "slip-d100", "amount": "5000.00", "by": "thip"}).status_code == 200
    assert client.post("/v1/pipeline/%s/gates/epc-confirmed" % uid,
                       json={"confirmed_on": str(settings.business_date), "source": "ODOO"}).status_code == 200

    # EPC is recorded but no longer blocks: with down payment passed, only contract
    # signed is named as an open condition.
    refused = client.post("/v1/pipeline/%s:release" % uid, json={"by": "thip"})
    assert refused.status_code == 422 and refused.json()["code"] == "gate_not_passed"
    assert refused.json()["extensions"]["gates"] == ["contract_signed"]

    assert client.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % uid,
                       json={"note": "สำเนาสัญญาที่ลงนามทั้งสองฝ่าย", "by": "thip"}).status_code == 201
    released = client.post("/v1/pipeline/%s:release" % uid, json={"by": "thip"})
    assert released.status_code == 201, released.json()
    row = released.json()["item"]
    # The after-release card still reads the EPC date and its gate dict.
    assert row["gate_epc_confirmed"]["state"] == "PASSED"
    assert row["confirmed_install_on"] == str(settings.business_date)
    assert all(c["state"] == "PASSED" for c in row["conditions"])


# --- UAT 2026-09-18: a write response must carry the state it just wrote -----------------

def test_the_down_payment_gate_response_carries_the_condition_it_passed():
    """UAT failure 1/2: the gate answered 200 with the pre-write `conditions`
    (down_payment=OPEN), so the chip stayed "ยังไม่ยืนยัน" until a reload. The
    response item must already read PASSED — the same shape every read serves."""
    from app.config import settings

    item = _unreleased_with_amount()
    uid = item["uid"]
    before = next(c for c in item["conditions"] if c["key"] == "down_payment")
    assert before["state"] == "OPEN"

    r = client.post("/v1/pipeline/%s/gates/down-payment" % uid,
                    json={"slip_ref": "slip-regression-1", "amount": "5000.00", "by": "thip"})
    assert r.status_code == 200, r.json()
    row = r.json()["item"]
    down = next(c for c in row["conditions"] if c["key"] == "down_payment")
    assert down["state"] == "PASSED" and down["passed"] is True
    assert row["gate_down_payment"] == {"state": "PASSED", "ref": "slip-regression-1",
                                        "on": str(settings.business_date), "by": "thip"}
    # And the same item on the list route reads the same, not a second shape.
    listed = next(i for i in client.get("/v1/pipeline", params={"all": "true"}).json()["items"]
                  if i["uid"] == uid)
    assert next(c for c in listed["conditions"] if c["key"] == "down_payment")["state"] == "PASSED"


def test_the_evidence_attach_response_carries_the_condition_it_flipped():
    """The attach path already annotated after its write; this pins it so the UAT
    class of bug (a write answering with the pre-write conditions) cannot return."""
    uid = _unreleased_with_amount()["uid"]
    made = client.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % uid,
                       json={"note": "สำเนาสัญญาที่ลงนามทั้งสองฝ่าย", "by": "thip"})
    assert made.status_code == 201, made.json()
    body = made.json()
    signed = next(c for c in body["item"]["conditions"] if c["key"] == "contract_signed")
    assert signed["state"] == "PASSED" and signed["passed"] is True
    assert signed["evidence_count"] == 1
    assert signed["evidence"][0]["uid"] == body["evidence"]["uid"]
    assert next(c for c in body["conditions"] if c["key"] == "contract_signed")["state"] == "PASSED"
