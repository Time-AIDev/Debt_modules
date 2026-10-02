"""D02 / Q7 — the PEAK-vs-Odoo field compare (feedback-r2 TASK-206). Pure.

The four cases the target mockup draws: a Thai-vs-Latin name, a disagreeing volt id,
a disagreeing system size, and an equal value. Every test here is an ADDITION.
"""
from app.pipelines import peak_conflicts


def _inv(**over):
    row = {"doc_no": "IVT-1", "contact_code": "VL0010158", "reference": None,
           "customer_name": "Somchai Tamdee", "product_group": "Solar Leasing",
           "product_name": "Solar Rooftop 3 Phase_5.00kWp"}
    row.update(over)
    return row


IDENTITY = {"name_th": "สมชาย ธรรมดี", "name_roman": "Somchai Tamdee",
            "volt_id": "VL0010158_head", "customer_no": "28005096535",
            "product": "LEASE", "order": {"watt": "5000"}}


def _by_field(rows):
    return {r["field"]: r for r in rows}


def test_a_thai_vs_latin_name_is_a_conflict():
    rows = _by_field(peak_conflicts.compare(_inv(customer_name="Worarut Sangtong"), IDENTITY))
    assert rows["customer_name"]["same"] is False
    assert rows["customer_name"]["peak_value"] == "Worarut Sangtong"


def test_a_name_in_either_script_is_the_same_person():
    rows = _by_field(peak_conflicts.compare(_inv(customer_name="khun Somchai Tamdee"), IDENTITY))
    assert rows["customer_name"]["same"] is True


def test_a_disagreeing_volt_id_is_a_conflict():
    rows = _by_field(peak_conflicts.compare(_inv(contact_code="VRC0000022"), IDENTITY))
    assert rows["volt_id"]["same"] is False
    assert rows["volt_id"]["peak_value"] == "VRC0000022"
    assert rows["volt_id"]["odoo_value"] == "VL0010158_head"


def test_a_disagreeing_system_size_is_a_conflict():
    rows = _by_field(peak_conflicts.compare(_inv(product_name="Solar_6.25kWp"), IDENTITY))
    assert rows["system_size_kwp"] == {"field": "system_size_kwp", "odoo_value": "5.00",
                                       "peak_value": "6.25", "same": False}


def test_an_equal_value_is_not_a_conflict():
    rows = _by_field(peak_conflicts.compare(_inv(customer_name="สมชาย ธรรมดี"), IDENTITY))
    assert rows["customer_name"]["same"] is True
    assert rows["volt_id"]["same"] is True
    assert rows["system_size_kwp"]["same"] is True
    assert rows["product"]["same"] is True


def test_a_field_either_side_lacks_is_skipped_never_guessed():
    rows = peak_conflicts.compare(_inv(product_group="", product_name="Uninstall fee",
                                       customer_name=None, contact_code=None, reference=None),
                                  {"name_th": None, "name_roman": None, "volt_id": None,
                                   "customer_no": None, "product": None, "order": {}})
    assert rows == []
