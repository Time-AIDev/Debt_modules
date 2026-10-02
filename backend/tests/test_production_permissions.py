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
