"""Language pass: every Thai display string the SOP walkthrough serves has an English
twin that is non-empty, carries no Thai script and names no internal code."""
import re

from app import sop

THAI = re.compile(r"[฀-฾เ-๿]")
CODE = re.compile(r"\b(CF1|C3|C5|R12|D2[67]|OD-\d+|OQ-\d+|SVC-\d+|REQ-[A-Z]+-\d+|DEBT-[A-Z]+-\d+|W10|S12)\b|[Rr]uling \d+")


def _twins(node, path="$"):
    if isinstance(node, dict):
        for k, v in node.items():
            if k.endswith("_th") and isinstance(v, str) and v:
                en = node.get(k[:-3] + "_en")
                yield "%s.%s" % (path, k), en
            yield from _twins(v, "%s.%s" % (path, k))
    elif isinstance(node, (list, tuple)):
        for i, v in enumerate(node):
            yield from _twins(v, "%s[%d]" % (path, i))


def _pipe(**kw):
    return dict({"uid": "pip-1", "gate_down_payment": {"state": "OPEN"},
                 "gate_epc_confirmed": {"state": "OPEN"}, "history": []}, **kw)


PASSED = {"state": "PASSED"}
LOCKED = {"contact_lock": {"state": "LOCKED", "locked_by": "thip", "locked_at_local_th": "23/10/2026 เวลา 09:12 น."},
          "ladder": {"mode": "ASSISTED", "indicative": "NOTICE_30"}}
BASE = {"customer_uid": "c-1"}

PAYLOADS = [
    sop.walkthrough(BASE, in_book=False),
    sop.walkthrough(BASE, pipeline_item=_pipe(), in_book=False),
    sop.walkthrough(BASE, pipeline_item=_pipe(gate_down_payment=PASSED), in_book=False),
    sop.walkthrough(BASE, pipeline_item=_pipe(gate_epc_confirmed=PASSED), in_book=False),
    sop.walkthrough(BASE, pipeline_item=_pipe(gate_down_payment=PASSED, gate_epc_confirmed=PASSED), in_book=False),
    sop.walkthrough(BASE, pipeline_item=_pipe(gate_down_payment=PASSED, gate_epc_confirmed=PASSED, released_at="x"), in_book=False),
    sop.walkthrough(BASE, pipeline_item=_pipe(gate_down_payment=PASSED, gate_epc_confirmed=PASSED, released_at="x", delivery={}), in_book=False),
    sop.walkthrough(BASE, pipeline_item=_pipe(gate_down_payment=PASSED, gate_epc_confirmed=PASSED, released_at="x", delivery={"a": 1}), in_book=False),
    sop.walkthrough(BASE, pipeline_item=_pipe(gate_down_payment=PASSED, gate_epc_confirmed=PASSED, released_at="x", delivery={"a": 1}, install_outcome="POSTPONED"), in_book=False),
    sop.walkthrough(BASE, pipeline_item=_pipe(gate_down_payment=PASSED, gate_epc_confirmed=PASSED, released_at="x", delivery={"a": 1}, install_outcome="INSTALLED"), in_book=False),
    sop.walkthrough(dict(BASE, payment_status="CLOSED")),
    sop.walkthrough(dict(BASE, payment_status="NPL")),
    sop.walkthrough(dict(BASE, payment_status="NPL", npl_type="LEGAL"), item={"ladder": {"mode": "MANUAL"}}),
    sop.walkthrough(dict(BASE, dc_status="RESTRUCTURE_LOAN")),
    sop.walkthrough(dict(BASE, review_uid="rv-1")),
    sop.walkthrough(dict(BASE, open_issue_uid="is-1")),
    sop.walkthrough(dict(BASE, open_ptp_uid="p-1")),
    sop.walkthrough(dict(BASE, broken_ptp_count=1)),
    sop.walkthrough(dict(BASE, broken_ptp_count=1, renegotiation_count=2)),
    sop.walkthrough(BASE, item=dict(LOCKED, unreachable_run={"unreachable_since_last_reach": 2})),
    sop.walkthrough(dict(BASE, next_action="SEND_REMINDER")),
    sop.walkthrough(dict(BASE, next_action="CONFIRM_SLIP")),
    sop.walkthrough(dict(BASE, payment_status="LATE"), item=LOCKED),
    sop.walkthrough(dict(BASE, payment_status="LATE")),
    sop.walkthrough(dict(BASE, payment_status="CURRENT")),
    sop.walkthrough(dict(BASE, payment_status="PAID")),
]


def test_every_walkthrough_placement_carries_english_twins():
    seen = 0
    for payload in PAYLOADS + [list(sop.STEPS), sop.D26, sop.D27, sop.SOURCE]:
        for where, en in _twins(payload):
            seen += 1
            assert isinstance(en, str) and en.strip(), where
            assert not THAI.search(en), (where, en)
            assert not CODE.search(en), (where, en)
    assert seen > 150


def test_the_seventeen_steps_have_english_rules_and_lanes():
    assert {p["step"] for p in PAYLOADS if p["step"]} >= {1, 2, 3, 5, 6, 8, 10, 11, 12, 13, 14, 15, 16}
    for s in sop.STEPS:
        assert s["gate_rule_en"] and s["name_en"] and sop.LANE_EN[s["lane"]], s["code"]
