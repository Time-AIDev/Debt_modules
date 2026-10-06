"""§3 and §4 of the rules file, one test per row of those tables."""
from decimal import Decimal

import pytest

from app.pipelines import crm_lead, rules as rules_mod

RULES = rules_mod.load()


def eligible(row):
    return dict(row, stage_name="Won", epc_start_date="2024-06-01",
                epc_end_date="2024-07-01")


def test_a_two_digit_year_is_day_first():
    # import_master_sheet.py's own rule: 02/05/24 is 2 May, not 5 February.
    assert crm_lead.as_date("02/05/24") == "2024-05-02"
    assert crm_lead.as_date("2/5/2024") == "2024-05-02"
    assert crm_lead.as_date("2024-05-02T00:00:00") == "2024-05-02"
    assert crm_lead.as_date("") is None
    # 2026-09-25: one shared parser (parsing.day_first_date). A value that is not a
    # real date refuses its lead (date_unreadable) instead of reading as "no date".
    with pytest.raises(ValueError):
        crm_lead.as_date("not a date")
    with pytest.raises(ValueError):
        crm_lead.as_date("31/02/2026")


def test_month_year_cells_from_both_systems():
    assert crm_lead.as_month("05/24") == "2024-05"
    assert crm_lead.as_month("May 2024") == "2024-05"
    assert crm_lead.as_month("2024-05") == "2024-05"


def test_a_phone_key_is_the_last_nine_digits():
    assert crm_lead.phone_key("+66 92 542 3597") == "925423597"
    assert crm_lead.phone_key("0925423597") == "925423597"
    assert crm_lead.phone_key("123") == ""


def test_money_drops_the_baht_sign_and_the_thousands_comma():
    assert crm_lead.as_money("3,199฿") == Decimal("3199.00")
    assert crm_lead.as_money("") is None


def test_a_listed_code_is_translated_and_says_so():
    assert crm_lead.translate("com_status", "paid_out", RULES) == ("Paid Out", True)
    assert crm_lead.translate("stage_name", "Won", RULES) == ("Order - Done", True)
    assert crm_lead.translate("connection_type", "single_phase", RULES) == ("1", True)


def test_an_unlisted_code_is_title_cased_and_flagged_as_unmapped():
    # 22 of the 23 crm.stage values were never seen. They must surface as
    # "nobody wrote a rule for this", not as a silent guess.
    assert crm_lead.translate("stage_name", "qualified_lead", RULES) == (
        "Qualified Lead", False)


def test_a_row_with_neither_a_volt_id_nor_a_phone_is_rejected():
    assert crm_lead.rejection_for({"volt_id": "", "phone": ""}, set(), RULES) == "no_identity"


def test_a_row_with_only_a_phone_is_acceptable():
    # keyed by its Odoo id (lead-<id>), so the id is part of the identity now
    assert crm_lead.rejection_for({"id": 1, "volt_id": "", "phone": "0925423597"},
                                  set(), RULES) is None


def test_a_volt_id_of_neither_shape_is_rejected():
    assert crm_lead.rejection_for({"volt_id": "banana", "phone": "0925423597"},
                                  set(), RULES) == "unshaped_volt_id"


def test_both_real_volt_id_shapes_are_accepted():
    # Odoo holds two: the sheet's long form and its own VL/VC form.
    assert crm_lead.rejection_for({"volt_id": "99999000032_Testperson_x_IPW"},
                                  set(), RULES) is None
    assert crm_lead.rejection_for({"volt_id": "VL0000143"}, set(), RULES) is None


def test_a_duplicate_volt_id_in_one_run_keeps_the_newer_lead_and_names_the_older():
    """Rules file §5: later row wins, earlier reported. The pull is ordered by Odoo id,
    so the later row is the newer lead — it lands, and the older one is refused under
    its own Odoo id."""
    rows = [eligible({"id": 3, "volt_id": "28000000001_A_x_IPW", "phone": "0812345678"}),
            eligible({"id": 4, "volt_id": "28000000001_B_y_IPW", "phone": "0812345679"})]
    records, verdicts = crm_lead.normalise(rows, RULES)
    assert [(r["volt_id"], r["order"]["crm_id"]) for r in records] == [("28000000001_B_y_IPW", 4)]
    assert verdicts[0] == {"volt_id": "28000000001_A_x_IPW", "verdict": "rejected",
                           "rule": "duplicate_volt_id", "unmapped": [], "odoo_id": 3}
    assert verdicts[1]["verdict"] == "landed" and verdicts[1]["odoo_id"] == 4


def test_the_stem_is_what_makes_the_two_shapes_one_key():
    assert crm_lead.volt_stem("99999000032_Testperson_x_IPW") == "99999000032"
    assert crm_lead.volt_stem("VL0000143") == "VL0000143"
    assert crm_lead.volt_stem("") == ""


RAW = [
    {"id": "74481", "volt_id": "VL0000143", "contact_name": "ทดลอง สมมติ",
     "last_name": "สมมติ", "phone": "0925423597", "email_from": "a@b.co",
     "stage_name": "Won", "connection_type": "single_phase", "epc": "IPW",
     "submitted_date": "2024-05-02", "contract_signed_date": "2024-05-24",
     "epc_start_date": "2024-06-01", "epc_end_date": "2024-07-01",
     "order_type": "leasing", "inverter_kw": "5.0", "monthly_rate": "0.0",
     "user_id": "70|North - Salestest", "zip": "10150"},
    eligible({"id": "74482", "volt_id": "", "phone": "", "contact_name": "no identity"}),
]


def test_defensive_eligibility_rejects_non_won_and_missing_install_dates():
    base = dict(RAW[0])
    rows = [
        dict(base, id="not-won", volt_id="VL0000141", stage_name="Qualified"),
        dict(base, id="no-start", volt_id="VL0000142", epc_start_date=False),
        dict(base, id="no-end", volt_id="VL0000143", epc_end_date=False),
        dict(base, id="eligible", volt_id="VL0000144"),
    ]
    records, verdicts = crm_lead.normalise(rows, RULES)
    assert [record["order"]["crm_id"] for record in records] == ["eligible"]
    assert [v["rule"] for v in verdicts] == [
        "not_won", "install_start_missing", "install_end_missing", None,
    ]


def test_every_landed_row_says_odoo_knows_of_no_money():
    records, _ = crm_lead.normalise(RAW, RULES)
    assert [r["reason"] for r in records] == ["no money row in Odoo"]


def test_a_record_carries_the_landing_customer_shape():
    records, _ = crm_lead.normalise(RAW, RULES)
    from app import landing
    for column in landing.CUSTOMER_COLUMNS:
        assert column in records[0]


def test_the_phone_is_kept_for_dialling_and_masked_for_showing():
    records, _ = crm_lead.normalise(RAW, RULES)
    assert records[0]["phone_e164"] == "0925423597"
    assert "x" in records[0]["phone_masked"]
    assert "5423597" not in records[0]["phone_masked"]


def test_social_ids_are_kept_as_link_only_customer_fields():
    row = dict(RAW[0], line_id="line-volt-143", meta_id="facebook.volt.143")
    record = crm_lead.normalise([row], RULES)[0][0]
    assert record["line_id"] == "line-volt-143"
    assert record["meta_id"] == "facebook.volt.143"


def test_vocabulary_is_applied_to_the_order_block():
    records, _ = crm_lead.normalise(RAW, RULES)
    assert records[0]["order"]["order_status"] == "Order - Done"


def test_watt_comes_back_in_watts_not_kilowatts():
    # panel_watt is one panel; inverter_kw is the system, and the sheet writes W.
    records, _ = crm_lead.normalise(RAW, RULES)
    assert records[0]["order"]["watt"] == 5000


def test_a_rejected_row_is_reported_with_its_rule_and_never_landed():
    records, verdicts = crm_lead.normalise(RAW, RULES)
    assert len(records) == 1
    rejected = [v for v in verdicts if v["verdict"] == "rejected"]
    assert rejected == [{"volt_id": "", "verdict": "rejected",
                         "rule": "no_identity", "unmapped": [], "odoo_id": "74482"}]


def test_an_unmapped_vocabulary_value_travels_on_the_verdict():
    rows = [dict(RAW[0], connection_type="unknown_phase")]
    _, verdicts = crm_lead.normalise(rows, RULES)
    assert verdicts[0]["unmapped"] == [["connection_type", "unknown_phase"]]


def test_normalise_is_pure():
    before = [dict(r) for r in RAW]
    crm_lead.normalise(RAW, RULES)
    assert RAW == before


# --- what Odoo actually returns over JSON-RPC ------------------------------------
# The first live run died on `TypeError: expected string or bytes-like object`:
# Odoo sends inverter_kw as a float and an empty value as the boolean False, where
# every test above had handed these helpers a string. A helper that only survives
# its own fixtures is not tested.

def test_the_helpers_survive_odoo_json_types():
    assert crm_lead.as_money(5.0) == Decimal("5.00")
    assert crm_lead.as_money(0) == Decimal("0.00")
    assert crm_lead.as_money(False) is None
    assert crm_lead.as_date(False) is None
    assert crm_lead.as_month(False) is None
    assert crm_lead.phone_key(False) == ""
    assert crm_lead.translate("stage_name", False, RULES) == (False, True)


def test_a_row_of_odoo_json_types_normalises():
    rows = [eligible({"id": 74481, "volt_id": "VL0000143", "contact_name": False,
             "phone": False, "mobile": "0925423597", "email_from": False,
             "stage_name": "Won", "connection_type": False, "epc": False,
             "submitted_date": False, "inverter_kw": 5.0, "order_type": False,
             "user_id": [70, "North - Salestest"], "zip": False})]
    records, verdicts = crm_lead.normalise(rows, RULES)
    assert records[0]["order"]["watt"] == 5000
    assert records[0]["phone_e164"] == "0925423597"
    assert records[0]["sales_lead"] == "North - Salestest"
    assert verdicts[0]["verdict"] == "landed"


# --- what the first live run against 34,338 real leads taught --------------------
# 23,514 of them carry the literal string "New" as volt_id: Odoo's placeholder from
# before an id is minted. Rejecting those as "unshaped" threw away 70% of the book
# for a value that is not an id at all — and a lead with a phone still has an
# identity. And two real shapes were being refused: VRL/VRC, and the bare 11-digit
# CRM id with no underscore after it.

def test_the_placeholder_is_treated_as_no_id_not_as_a_bad_one():
    assert crm_lead.clean_volt_id("New") == ""
    assert crm_lead.clean_volt_id("new") == ""
    assert crm_lead.clean_volt_id("VL0000143") == "VL0000143"


def test_a_placeholder_lead_with_a_phone_lands_keyed_by_its_odoo_id_not_its_phone():
    """2026-09-25: the key used to be phone-<last 9 digits> — the mobile number,
    served by the registry and searchable. It is the crm.lead id now."""
    rows = [eligible({"id": 1, "volt_id": "New", "phone": "0925423597"})]
    records, verdicts = crm_lead.normalise(rows, RULES)
    assert verdicts[0]["verdict"] == "landed"
    assert records[0]["volt_id"] == "lead-1"
    assert records[0]["customer_no"] is None


def test_a_junk_phone_does_not_hide_a_good_mobile():
    rows = [eligible({"id": 2, "volt_id": "New", "phone": "-", "mobile": "0925423597"})]
    records, verdicts = crm_lead.normalise(rows, RULES)
    assert verdicts[0]["verdict"] == "landed"
    assert records[0]["phone_e164"] == "0925423597"


def test_an_unreadable_date_refuses_that_lead_by_its_odoo_id():
    rows = [eligible({"id": 5, "volt_id": "VL0000143", "submitted_date": "31/02/2026"}),
            eligible({"id": 6, "volt_id": "VL0000144", "submitted_date": "02/05/24"})]
    records, verdicts = crm_lead.normalise(rows, RULES)
    assert [r["volt_id"] for r in records] == ["VL0000144"]
    assert records[0]["order"]["submit_date"] == "2024-05-02"
    assert verdicts[0] == {"volt_id": "VL0000143", "verdict": "rejected",
                           "rule": "date_unreadable", "unmapped": [], "odoo_id": 5}


def test_a_placeholder_lead_with_no_phone_has_no_identity_at_all():
    rows = [eligible({"id": 1, "volt_id": "New", "phone": False})]
    _, verdicts = crm_lead.normalise(rows, RULES)
    assert verdicts[0] == {"volt_id": "", "verdict": "rejected",
                           "rule": "no_identity", "unmapped": [], "odoo_id": 1}


def test_every_real_volt_id_shape_odoo_holds_is_accepted():
    for shape in ("VL0000143", "99999000205", "VRL0000035", "99999000407",
                  "99999000001", "99999000032_Testperson_x_IPW"):
        assert crm_lead.rejection_for({"volt_id": shape}, set(), RULES) is None, shape


def test_something_that_is_genuinely_not_an_id_is_still_refused():
    assert crm_lead.rejection_for({"volt_id": "banana", "phone": "0925423597"},
                                  set(), RULES) == "unshaped_volt_id"


def test_an_unlisted_value_is_flagged_even_when_it_is_not_snake_case():
    # The first live run reported ZERO unmapped values across 34,336 leads, which
    # was not honesty but a hole: only snake_case fell through to the flag, so a
    # plain-word stage nobody wrote a rule for passed as though it had one.
    value, was_mapped = crm_lead.translate("stage_name", "Qualified", RULES)
    assert (value, was_mapped) == ("Qualified", False)
    # A listed one is still mapped, and an empty one is not a missing rule.
    assert crm_lead.translate("stage_name", "Won", RULES) == ("Order - Done", True)
    assert crm_lead.translate("stage_name", False, RULES) == (False, True)
    # A field with no vocabulary table at all is not a missing rule either.
    assert crm_lead.translate("epc", "IPW", RULES) == ("IPW", True)


def test_the_quote_odoo_holds_travels_on_the_order_to_read_never_to_bill():
    """2026-09-25: dp_amount / dp_percent / monthly_rate were pulled and dropped. They
    land as odoo_* keys: the sheet's own dp_amount is what the down-payment card bills.
    Odoo's `monthly_rate` holds the TERM in months (60, 48 …), never baht."""
    row = eligible({"id": "90001", "volt_id": "VL0009001", "phone": "0800000001",
                    "dp_amount": 14900.0, "dp_percent": 10.0, "monthly_rate": 60.0})
    order = crm_lead.normalise([row], RULES)[0][0]["order"]
    assert (order["odoo_dp_amount"], order["odoo_dp_pct"], order["odoo_term"]) == ("14900.00", "10.00", 60)
    assert not {"dp_amount", "dp_pct", "term", "monthly_rate_inc_vat"} & set(order)
    empty = crm_lead.normalise([dict(row, dp_amount=0.0, dp_percent=False, monthly_rate=0.0)], RULES)[0][0]["order"]
    assert (empty["odoo_dp_amount"], empty["odoo_dp_pct"], empty["odoo_term"]) == (None, None, None)


def test_the_exact_odoo_lead_title_survives_normalisation():
    row = dict(RAW[0], name='28006752779_Danudech_ดนุเดช เลขะสันต์_VOLT')
    records, _ = crm_lead.normalise([row], RULES)
    assert records[0]['order']['odoo_lead_name'] == '28006752779_Danudech_ดนุเดช เลขะสันต์_VOLT'
