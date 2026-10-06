import pytest
from app import errors, production_permissions


def test_officer_cannot_mutate_another_assignment():
    with pytest.raises(errors.Problem) as refusal:
        production_permissions.require_assignment({"role": "OFFICER", "officer": "thip"}, "nantapol")
    assert refusal.value.status == 403


def test_own_assignment_and_manager_supervision_are_allowed():
    production_permissions.require_assignment({"role": "OFFICER", "officer": "thip"}, "thip")
    production_permissions.require_assignment({"role": "MANAGER", "officer": "manager"}, "nantapol")


def test_unassigned_case_is_not_an_officers_write_permission():
    with pytest.raises(errors.Problem):
        production_permissions.require_assignment({"role": "OFFICER", "officer": "thip"}, None)


def test_ops_cannot_create_a_promise_embedded_in_an_otherwise_allowed_contact():
    template = "/v1/cases/by-customer/{customer_uid}/contacts"
    with pytest.raises(errors.Problem) as refused:
        production_permissions._role_gate(template, {"role": "OPS"}, {"ptp": {"amount": "100", "date": "2026-10-24"}})
    assert refused.value.status == 403
    production_permissions._role_gate(template, {"role": "OPS"}, {"issue": {"summary": "Service inspection"}})


@pytest.mark.parametrize("role", ["OPS", "OFFICER", "SUPERVISOR", "MANAGER", "OWNER"])
def test_contact_promise_uses_the_same_roles_as_standalone_promises(role):
    from fastapi.testclient import TestClient
    from app import cases, main
    from app.config import settings
    from datetime import timedelta
    uid = next(uid for uid, case in cases.for_current().cases.items() if not case.get("open_ptp_uid"))
    body = {"result": "REACHED_PTP", "ptp": {"amount": "100", "date": str(settings.business_date + timedelta(days=1))}}
    before = len(cases.for_current().ptps)
    with TestClient(main.app) as client:
        response = client.post("/v1/cases/by-customer/" + uid + "/contacts", json=body,
                               headers={"X-Volt-Role": role})
        state = client.get("/v1/cases/by-customer/" + uid).json()
    assert response.status_code == (403 if role == "OPS" else 201)
    assert len(state["ptps"]) == (0 if role == "OPS" else 1)
    if role == "OPS":
        assert len(cases.for_current().ptps) == before


@pytest.mark.parametrize("path", ["/v1/case-ptps/child:close", "/v1/contacts/child:correct",
                                   "/v1/reviews/child:answer", "/v1/case-issues/child:close",
                                   "/v1/power-restrictions/child:restore"])
def test_child_identifier_cannot_bypass_case_assignment(monkeypatch, path):
    from types import SimpleNamespace
    from app import cases
    child = {"uid": "child", "customer_uid": "other"}
    state = SimpleNamespace(cases={"other": {"uid": "case-other", "customer_uid": "other", "officer_uid": "nantapol"}},
                            ptps={"child": child}, reviews={"child": child}, issues={"child": child},
                            power={"child": child}, contact_log=[child], today_items=[])
    monkeypatch.setattr(cases, "for_current", lambda: state)
    with pytest.raises(errors.Problem) as refused:
        production_permissions.enforce({"type": "http", "path": path, "method": "POST"},
                                       {"role": "OFFICER", "officer": "thip"}, b'{}')
    assert refused.value.status == 403
