"""The chain itself: ordering, hashing, and what verify() can prove."""
import pytest

from app import audit


def a_chain():
    chain = audit.Chain()
    chain.append(actor_claimed="nantapol", actor_source="HEADER", verb="POST",
                 route_template="/v1/cases/by-customer/{customer_uid}/dc-status",
                 act="DC_STATUS_SET", subject_type="customer", subject_uid="cus-42",
                 detail={"from": "CONTACT_BACK", "to": "PAID", "reason": "ชำระแล้ว"},
                 outcome="OK", status=200, error_code=None,
                 session_id="s-1", request_id="r-1")
    chain.append(actor_claimed="thip", actor_source="BODY", verb="POST",
                 route_template="/v1/contacts", act=None, subject_type=None,
                 subject_uid=None, detail={}, outcome="REFUSED", status=422,
                 error_code="next_action_required", session_id="s-1", request_id="r-2")
    return chain


def test_the_first_entry_chains_from_genesis_and_seq_starts_at_one():
    chain = audit.Chain()
    entry = chain.append(actor_claimed="nantapol", actor_source="HEADER", verb="POST",
                         route_template="/v1/x", act=None, subject_type=None,
                         subject_uid=None, detail={}, outcome="OK", status=200,
                         error_code=None, session_id="s", request_id="r")
    assert entry["seq"] == 1
    assert entry["prev_hash"] == audit.GENESIS
    assert len(entry["hash"]) == 64


def test_each_entry_chains_from_the_one_before():
    chain = a_chain()
    first, second = chain.entries()
    assert second["seq"] == 2
    assert second["prev_hash"] == first["hash"]


def test_a_clean_chain_verifies_and_reports_what_it_checked():
    result = a_chain().verify()
    assert result["ok"] is True
    assert result["verified"] == 2
    assert result["broken_at"] is None


def test_altering_a_field_breaks_the_chain_at_that_entry():
    chain = a_chain()
    # The exact tamper an audit log exists to catch: a reason quietly rewritten.
    chain.entries()[0]["detail"]["reason"] = "something else"
    result = chain.verify()
    assert result["ok"] is False
    assert result["broken_at"] == 1


def test_removing_an_entry_breaks_the_chain_at_its_successor():
    chain = a_chain()
    del chain.entries()[0]
    result = chain.verify()
    assert result["ok"] is False
    assert result["broken_at"] == 2


def test_the_same_entry_always_hashes_the_same_regardless_of_key_order():
    one = {k: v for k, v in [("a", 1), ("b", {"x": 1, "y": 2})]}
    two = {k: v for k, v in [("b", {"y": 2, "x": 1}), ("a", 1)]}
    assert audit.canonical(one) == audit.canonical(two)


def test_a_failed_write_is_counted_and_verify_reports_it():
    chain = a_chain()
    chain.record_gap("database unreachable")
    result = chain.verify()
    # The chain is INTACT — nothing was altered — but it is not COMPLETE, and
    # those are different claims. A reader must be able to tell them apart.
    assert result["ok"] is True
    assert result["gaps"] == 1
    assert result["complete"] is False


def test_a_field_the_chain_cannot_hash_is_refused_not_dropped():
    chain = audit.Chain()
    # An unhashed field is an unprotected field, so unknown keys must raise
    # rather than silently disappear.
    with pytest.raises(ValueError, match="fields the chain does not hash"):
        chain.append(actor_claimed="nantapol", actor_source="HEADER", verb="POST",
                     route_template="/v1/x", act=None, subject_type=None,
                     subject_uid=None, detail={}, outcome="OK", status=200,
                     error_code=None, session_id="s", request_id="r",
                     unknown_field="should not be accepted")
    # Verify a normal append with only known keys still works.
    entry = chain.append(actor_claimed="nantapol", actor_source="HEADER", verb="POST",
                         route_template="/v1/x", act=None, subject_type=None,
                         subject_uid=None, detail={}, outcome="OK", status=200,
                         error_code=None, session_id="s", request_id="r")
    assert entry["seq"] == 1


def test_an_empty_chain_verifies_as_intact_and_complete():
    chain = audit.Chain()
    result = chain.verify()
    assert result["ok"] is True
    assert result["verified"] == 0
    assert result["broken_at"] is None
    assert result["complete"] is True
