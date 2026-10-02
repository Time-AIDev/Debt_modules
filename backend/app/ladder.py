"""The deck's ladders — data, not automation.

SOURCE OF THE RUNGS: deck "VOLT ERP — SPV/EPC Scenario Workflows v20.0" (S07, S11).
The ladder is a different instrument from the aging band sets in money/band_sets.py:
a band answers "how old is the arrears"; a rung is a contractual ACT (notice,
restructure offer, NPL declaration, assignment). Do not add a band set for it and
do not conflate a rung with a bucket (spec-deltas-v25-rebuild.md §2.3).

This module only ever computes an INDICATIVE rung. The actual stage of a case moves
by explicit human POST — OD-04's own note: "NPL is never automatic — the system
raises the review, a human flags." Under ladder_mode=MANUAL even the indicative
rung is withheld (R6, grilling 2026-08-30).
"""

SOURCE = "VOLT ERP — SPV/EPC Scenario Workflows v20.0"

MODE_ASSISTED = "ASSISTED"
MODE_MANUAL = "MANUAL"
LADDER_MODES = (MODE_ASSISTED, MODE_MANUAL)

# Each rung: stage code, day threshold (the deck's calendar mirror), the minimum
# missed-instalment count the deck words the rung in, and what the rung IS.
LEASE_LADDER = (
    {"stage": "NOTICE_30", "day": 30, "min_missed": 1,
     "act": "Notice and cure", "act_th": "แจ้งเตือนและให้เวลาชำระ", "act_en": "Notice and time to pay"},
    {"stage": "RESTRUCTURE_OFFER_60", "day": 60, "min_missed": 2,
     "act": "Restructure OFFERED (S08)", "act_th": "เสนอปรับโครงสร้างหนี้", "act_en": "Offer to restructure the debt"},
    {"stage": "NPL_DECLARED_90", "day": 90, "min_missed": 2,
     "act": "NPL declared — provisioning only, the contract is not moved yet",
     "act_th": "ประกาศ NPL (ตั้งสำรองเท่านั้น)", "act_en": "Declare NPL (provisioning only)"},
    {"stage": "ASSIGNED_120", "day": 120, "min_missed": 2,
     "act": "Assignment deed executed — EPC pays SPV 100% of remaining NPV",
     "act_th": "โอนสัญญากลับ EPC (buyback 100% ของ NPV คงเหลือ)",
     "act_en": "Assign the contract back to EPC (buyback at 100% of remaining NPV)"},
)

CASH_LADDER = (
    {"stage": "NOTICE_30", "day": 30, "min_missed": 1,
     "act": "Notice and cure", "act_th": "แจ้งเตือนและให้เวลาชำระ", "act_en": "Notice and time to pay"},
    {"stage": "SETTLEMENT_PLAN_60", "day": 60, "min_missed": 1,
     "act": "Settlement plan offered", "act_th": "เสนอแผนผ่อนชำระยอดคงค้าง", "act_en": "Offer a plan to pay off the arrears"},
    {"stage": "DEFAULT_CONFIRMED_90", "day": 90, "min_missed": 1,
     "act": "Default confirmed — legal claim or removal",
     "act_th": "ยืนยันผิดนัด — ฟ้องร้องหรือถอดระบบ", "act_en": "Confirm default — legal claim or removal"},
)

SERVICE_DUNNING = (
    {"stage": "SVC_OVERDUE", "day": 1, "min_missed": 1,
     "act": "Service invoice overdue — EPC's own dunning",
     "act_th": "ค่าบริการค้างชำระ (EPC ติดตามเอง)", "act_en": "Service fee overdue (EPC collects it)"},
    {"stage": "SVC_DUNNING", "day": 30, "min_missed": 1,
     "act": "Service dunning — never feeds the lease NPL ladder",
     "act_th": "ทวงถามค่าบริการ (ไม่เข้าบันได NPL)", "act_en": "Service fee reminder (outside the NPL ladder)"},
)

LADDERS = {"LEASE": LEASE_LADDER, "CASH": CASH_LADDER, "SERVICE": SERVICE_DUNNING}

# Ordering for "deepest ladder step" in the R11 priority tiers.
_DEPTH = {}
for _kind, _rungs in LADDERS.items():
    for _i, _rung in enumerate(_rungs, start=1):
        _DEPTH[_rung["stage"]] = _i
_DEPTH["NORMAL"] = 0


def stage_depth(stage) -> int:
    return _DEPTH.get(stage or "NORMAL", 0)


def indicative_stage(kind: str, dpd, missed: int):
    """The highest rung whose day threshold the DPD has reached AND whose
    missed-count wording holds. None (never a stage string) when nothing has.
    Purely indicative — see the module docstring."""
    if dpd is None:
        return None
    best = None
    for rung in LADDERS[kind]:
        if dpd >= rung["day"] and (missed or 0) >= rung["min_missed"]:
            best = rung["stage"]
    return best


def ladder_rungs():
    """The rungs a client may name, once each. LEASE order first, then the CASH rungs
    LEASE does not have; NOTICE_30 is shared and carries both kinds. Ordered, not a set:
    the interface prints them as a list and must not re-order the deck's calendar.
    Round-4 F2-CR-1: SERVICE_DUNNING is deliberately excluded — service-fee arrears
    never feed the lease NPL ladder, so a SVC_* rung is not a value this filter takes."""
    rungs, by_stage = [], {}
    for kind in ("LEASE", "CASH"):
        for rung in LADDERS[kind]:
            seen = by_stage.get(rung["stage"])
            if seen:
                if kind not in seen["kinds"]:
                    seen["kinds"].append(kind)
                continue
            by_stage[rung["stage"]] = {"stage": rung["stage"], "day": rung["day"],
                                       "act_th": rung["act_th"], "act_en": rung["act_en"],
                                       "kinds": [kind]}
            rungs.append(by_stage[rung["stage"]])
    return rungs


def ladder_payload(kind: str, actual_stage, dpd, missed, mode=MODE_ASSISTED, markers=None):
    """What the wire carries. The interface draws ONLY this — it never derives a
    rung from a DPD (the no-arithmetic rule)."""
    return {
        "kind": kind,
        "steps": [
            {"stage": r["stage"], "day": r["day"], "act": r["act"], "act_th": r["act_th"],
             "act_en": r["act_en"]}
            for r in LADDERS[kind]
        ],
        "stage": actual_stage or "NORMAL",
        "indicative": (indicative_stage(kind, dpd, missed)
                       if mode == MODE_ASSISTED else None),
        "mode": mode,
        "markers": markers or {},
        "source": SOURCE,
        "pending_decision": "OD-04",
        "note": "Stages move only by human action; the indicative rung is not a decision.",
    }
