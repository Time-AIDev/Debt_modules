"""Arina, 2026-09-25: every tab of the New Order Master is read, but when a VOLT ID
sits on more than one, 'Done - Collection' / 'Done - Cash' win. Before this, the
cash tab read LAST won (so 'Done - Cash Old' beat 'Done - Cash') and the "fullest"
leasing snapshot won (so a backup tab could beat 'Done - Collection')."""
from app import imports

IMS = imports._IMS
VID = "28000000001_Test_ทดสอบ_IPW"


def _lease(sheet, status, term, months):
    return {"volt_id": VID, "source_ref": {"sheet": sheet, "row": 7}, "sales_lead": None,
            "term_original": term, "months": months, "maplog": [], "payment_status": status}


def _cash(sheet, comment):
    return {"volt_id": VID, "source_ref": {"sheet": sheet, "row": 7}, "sales_lead": None,
            "dc_comment": comment, "months": []}


def _payload(leasing=(), cash=()):
    return IMS.assemble_payload(list(leasing), list(cash), [], [], [], [], [], [], [], {}, [], [])


def test_done_collection_beats_a_fuller_backup_tab():
    paid = {"kind": "PAID", "amount": "3199"}
    done = _lease("Done - Collection", "Late", None, [paid])
    backup = _lease("Backup Done before 12_03 restor", "Current", 96, [paid, paid, paid])
    for order in ([done, backup], [backup, done]):
        c = _payload(leasing=order)["customers"][0]
        assert c["leasing"]["payment_status"] == "Late"


def test_done_cash_beats_done_cash_old_read_after_it():
    c = _payload(cash=[_cash(" Done - Cash ", "Close"), _cash("Done - Cash Old", None)])["customers"][0]
    assert c["cash"]["dc_comment"] == "Close"


def test_without_a_done_tab_the_old_rules_hold():
    paid = {"kind": "PAID", "amount": "1"}
    a = _lease("EPC - Collection", "Late", None, [paid])
    b = _lease("Absolete collection", "Current", 96, [paid])
    assert _payload(leasing=[a, b])["customers"][0]["leasing"]["payment_status"] == "Current"
    c = _payload(cash=[_cash("Done - Cash Old", "x"), _cash("DC other", "y")])["customers"][0]
    assert c["cash"]["dc_comment"] == "y"


def test_done_collection_status_beats_the_tracking_category():
    """The sheet's status on the case is Done - Collection's Payment Status where that
    tab carries the customer; a tracking tab's Category only where it does not."""
    from types import SimpleNamespace
    from app import cases
    tracking = {"category": "Active", "months": []}
    done = SimpleNamespace(sheet={"leasing": _lease("Done - Collection", "Late", 96, []), "tracking": tracking})
    assert cases.sheet_says(done) == ("LATE", "Late")
    other = SimpleNamespace(sheet={"leasing": _lease("EPC - Collection", "Late", 96, []), "tracking": tracking})
    assert cases.sheet_says(other) == ("CURRENT", "Active")
