"""PKD-001..008 — the PEAK draft-only contract (decision C3, REQ-ACC-030..034)."""
import inspect

import pytest

from app import peak_documents as pkd
from app.config import settings
from app.integrations import peak as peak_client


FORBIDDEN = ("approve", "post_", "update", "delete", "void", "issue")


@pytest.fixture
def state():
    pkd.reset()
    s = pkd.for_current()
    s.transport = pkd.StubTransport()
    yield s
    pkd.reset()


def test_pkd_001_the_client_has_two_verbs_and_nothing_else():
    public = [n for n, f in inspect.getmembers(peak_client, inspect.isfunction)
              if not n.startswith("_") and f.__module__ == peak_client.__name__]
    assert set(public) == {"probe", "create_draft", "read_state", "status"}, public
    for name in [n for n, _ in inspect.getmembers(pkd, inspect.isfunction)]:
        assert not any(bad in name.lower() for bad in FORBIDDEN), name


def test_pkd_002_the_key_is_stored_before_the_call(state):
    state.transport = pkd.StubTransport(fail_create=True)
    [record] = pkd.raise_document(state, "INVOICE_CREATE", "inv-1", "SPV", {"amount": "3199.00"}, by="thip")
    assert record["state"] == "UNSENT"
    assert record["idempotency_key"] in state.by_key      # stored even though the call failed


def test_pkd_003_a_replay_never_creates_twice(state):
    a = pkd.raise_document(state, "INVOICE_CREATE", "inv-1", "SPV", {"amount": "3199.00"}, by="thip")
    b = pkd.raise_document(state, "INVOICE_CREATE", "inv-1", "SPV", {"amount": "3199.00"}, by="thip")
    assert a[0]["uid"] == b[0]["uid"]
    assert len(state.transport.creates) == 1
    assert state.transport.creates[0][1] == "SPV"


def test_pkd_004_unsent_is_resendable_and_nothing_else_is(state):
    state.transport = pkd.StubTransport(fail_create=True)
    [record] = pkd.raise_document(state, "RECEIPT_FULL", "rcpt-1", "EPC", {"amount": "5000.00"}, by="thip")
    state.transport = pkd.StubTransport()
    pkd.resend(state, record["uid"])
    assert record["state"] == "DRAFT_CREATED" and record["peak_ref"]
    with pytest.raises(pkd.PeakDocumentError) as err:
        pkd.resend(state, record["uid"])
    assert err.value.code == "document_state_conflict"


def test_pkd_005_rejection_carries_the_reason(state):
    [record] = pkd.raise_document(state, "RECEIPT_PARTIAL", "rcpt-2", "EPC", {"amount": "1000.00"}, by="thip")
    state.transport = pkd.StubTransport(reject_reason="slip belongs to another customer")
    pkd.refresh(state, record["uid"])
    assert record["state"] == "REJECTED" and "another customer" in record["rejection_reason"]


def test_pkd_005b_approval_carries_number_and_qr_and_unknown_stays_draft(state):
    [record] = pkd.raise_document(state, "INVOICE_CREATE", "inv-9", "EPC", {"amount": "120000.00"}, by="thip")
    assert record["qr_payload"] is None                       # no QR on a draft (PC3)
    state.transport = pkd.StubTransport(read_unknown=True)
    pkd.refresh(state, record["uid"])
    assert record["state"] == "DRAFT_CREATED"
    state.transport = pkd.StubTransport()
    pkd.refresh(state, record["uid"])
    assert record["state"] == "APPROVED_IN_PEAK" and record["peak_number"] and record["qr_payload"]


def test_pkd_006_the_restructure_raises_two_documents_and_either_can_be_unsent(state):
    [void] = pkd.raise_document(state, "RESTRUCTURE_VOID_SERIES", "rst-1", "SPV", {"amount": "0"}, by="settasak")
    state.transport = pkd.StubTransport(fail_create=True)
    [journal] = pkd.raise_document(state, "RESTRUCTURE_MODIFICATION_LOSS", "rst-1", "SPV", {"amount": "41347.27"}, by="settasak")
    assert void["state"] == "DRAFT_CREATED" and journal["state"] == "UNSENT"
    assert void["uid"] != journal["uid"]


def test_pkd_007_every_intent_has_one_instance_rule(state):
    assert set(pkd.INSTANCE_RULE) == set(pkd.INTENTS)
    assert len(pkd.INTENTS) == 23
    for intent in pkd.NEVER_POSTS:
        with pytest.raises(pkd.PeakDocumentError):
            pkd.raise_document(state, intent, "x", "EPC", {}, by="x")
    docs = pkd.raise_document(state, "BUYBACK_DEED_AND_PAYMENT", "deed-1", "SPV", {"amount": "186916.00"}, by="owner")
    assert {d["instance"] for d in docs} == {"EPC", "SPV"}
    with pytest.raises(pkd.PeakDocumentError) as err:
        pkd.raise_document(state, "INVOICE_CREATE", "inv-x", None, {"amount": "1"}, by="x")
    assert err.value.code == "entity_unresolved"


def test_penalty_invoicing_refuses_when_an_owner_disables_it(monkeypatch):
    """The gate is kept because ruling 87 made the flag Owner-tunable. Turned off, it
    must still refuse — and its reason must name the configuration, not CF1."""
    monkeypatch.setattr(settings, "penalty_invoicing_enabled", False)
    state = pkd.for_current()
    with pytest.raises(pkd.PeakDocumentError) as err:
        pkd.raise_document(state, "PENALTY_INVOICE", "k-1", "SPV", {"amount": "150"}, by="x")
    assert err.value.code == "feature_disabled"
    assert "CF1" not in str(err.value)


def test_write_mode_is_locked(state, monkeypatch):
    monkeypatch.setattr(settings, "peak_write_mode", "FULL")
    with pytest.raises(pkd.PeakDocumentError) as err:
        pkd.raise_document(state, "INVOICE_CREATE", "inv-2", "EPC", {"amount": "1"}, by="x")
    assert err.value.code == "peak_draft_only"


def test_r6_87_penalty_invoicing_is_live_and_creates_a_draft(state):
    """Ruling 87: CF1 is decided, so the gate opens. C3 still holds — what is created
    is a DRAFT; nothing here approves anything."""
    state = pkd.for_current()
    assert settings.penalty_invoicing_enabled is True
    records = pkd.raise_document(state, "PENALTY_INVOICE", "k-1", "SPV",
                                 {"amount": "236.85"}, by="x")
    assert records
    assert settings.peak_write_mode == "DRAFT_ONLY"


def test_r6_87_penalty_draft_carries_a_thai_note_naming_the_peak_divergence(state):
    """Our rate is 0.03 %/day (ruling 87); PEAK bills 0.3 %/day until AR changes PEAK's
    own setting. Aynaz approves these drafts, so she is the one person who can catch
    the gap — she should not have to derive it. A record is a dict, not an object:
    payload lives at record["payload"], not record.payload."""
    records = pkd.raise_document(state, "PENALTY_INVOICE", "k-1", "SPV",
                                 {"amount": "236.85"}, by="x")
    note = records[0]["payload"]["note_th"]
    assert "0.03" in note and "PEAK" in note
    assert len(note) <= 500          # PEAK's หมายเหตุ column caps at 500 characters (A5 §2b)


def test_r6_104_the_note_reaches_the_document_sent_to_the_transport(state):
    """Ruling 104: storage on record["payload"] is not proof of transmission — _send
    builds a FRESH dict for the transport from named keys, and a note not named there
    is silently dropped. Prove the note survives that rebuild by reading it back off
    the outbound document StubTransport actually received, not off the local record."""
    pkd.raise_document(state, "PENALTY_INVOICE", "k-2", "SPV", {"amount": "236.85"}, by="x")
    sent_document = state.transport.creates[0][2]
    assert "0.03" in sent_document["note_th"] and "PEAK" in sent_document["note_th"]
    assert len(sent_document["note_th"]) <= 500


def test_r6_104_the_note_is_absent_for_every_other_intent(state):
    """The note names a divergence specific to PENALTY_INVOICE. Prove it does not leak
    onto unrelated documents at either the record or the outbound-document layer."""
    [record] = pkd.raise_document(state, "INVOICE_CREATE", "inv-104", "SPV", {"amount": "100.00"}, by="x")
    assert record["payload"].get("note_th") is None
    assert state.transport.creates[0][2]["note_th"] is None


def test_r6_104_the_note_reaches_the_peak_api_request_body(state, monkeypatch):
    """One layer deeper still: integrations.peak.create_draft builds ANOTHER fresh dict
    — the literal PEAK API request body — from named keys again. A fix that stops at
    _send's dict would leave this one silently dropping the note a second time. Fake
    PEAK's transport (never a real network call) and read the note back off the JSON
    body this process would actually send."""
    for key in peak_client.REQUIRED_ENV:
        monkeypatch.setenv(key, "x")
    captured = {}

    class FakeResponse:
        status_code = 200
        content = b"{}"

        def json(self):
            return {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["body"] = json
        return FakeResponse()

    monkeypatch.setattr(peak_client.httpx, "post", fake_post)
    state.transport = None      # falls through to the real client (peak_client), not the stub
    pkd.raise_document(state, "PENALTY_INVOICE", "k-3", "SPV", {"amount": "236.85"}, by="x")
    note = captured["body"]["document"]["note_th"]
    assert "0.03" in note and "PEAK" in note
    assert len(note) <= 500


def test_a_success_answer_that_is_not_json_leaves_the_draft_unsent_and_resendable(state, monkeypatch):
    """Fix-all P10d (M9): a 2xx with a proxy page for a body raised out of the send and
    left the draft PENDING for ever — refresh kept it there and resend refused it."""
    for key in peak_client.REQUIRED_ENV:
        monkeypatch.setenv(key, "x")

    class ProxyPage:
        status_code, content, text = 200, b"<html>ok</html>", "<html>ok</html>"

        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(peak_client.httpx, "post", lambda *a, **k: ProxyPage())
    state.transport = None      # the real client, over the faked transport
    [record] = pkd.raise_document(state, "INVOICE_CREATE", "inv-9", "EPC", {"amount": "100.00"}, by="x")
    assert record["state"] == "UNSENT" and record["last_error"] == "PEAK answered without a readable body"
    state.transport = pkd.StubTransport()
    pkd.resend(state, record["uid"])
    assert record["state"] == "DRAFT_CREATED"
