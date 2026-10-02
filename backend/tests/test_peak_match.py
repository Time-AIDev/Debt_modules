"""The match ladder (vault note 10 §3 WP1). Every rung is a test; the order of the
rungs is a test; what never auto-applies is a test."""
import types
from app.pipelines import peak_match as pm

BOOK = pm.build_book_index([
    {"customer_no": "28005096535", "volt_id": "28005096535_Manop_มานพ ทดสอบ_IPW",
     "phone_e164": "+66812345678", "display_name": "มานพ ทดสอบ", "name_roman": "Manop"},
    {"customer_no": "28006083653", "volt_id": "VC0098765_Somchai_สมชาย ทำดี_SLT",
     "phone_e164": "+66898765432", "display_name": "สมชาย ทำดี", "name_roman": "Somchai"},
])
ODOO = pm.build_odoo_index([{"volt_id": "VL0010239", "phone_e164": "0812345678"}])


def _inv(**over):
    base = {"doc_no": "IV-1", "reference": None, "contact_code": None, "customer_name": None}
    base.update(over)
    return base


def test_rung_1_an_eleven_digit_contact_code_is_the_customer_number():
    v = pm.match([_inv(contact_code="28005096535")], BOOK, ODOO, {})[0]
    assert v == {"verdict": "EXACT", "rule": "CUSTOMER_NO", "customer_no": "28005096535", "candidates": []}


def test_rung_1_reads_the_reference_column_too():
    v = pm.match([_inv(reference="28005096535", contact_code="QO-20260600021")], BOOK, ODOO, {})[0]
    assert v["verdict"] == "EXACT" and v["rule"] == "CUSTOMER_NO"


def test_rung_2_a_v_id_matches_the_books_volt_id_prefix_case_and_space_insensitively():
    v = pm.match([_inv(contact_code=" vc0098765 ")], BOOK, ODOO, {})[0]
    assert v["verdict"] == "EXACT" and v["rule"] == "VOLT_ID" and v["customer_no"] == "28006083653"


def test_rung_3_a_v_id_the_book_lacks_goes_through_odoos_phone():
    v = pm.match([_inv(contact_code="VL0010239")], BOOK, ODOO, {})[0]
    assert v["verdict"] == "EXACT" and v["rule"] == "VOLT_ID_VIA_ODOO_PHONE"
    assert v["customer_no"] == "28005096535"


def test_rung_0_a_confirmed_link_wins_over_every_other_rung():
    links = {"VC0098765": {"customer_no": "28005096535"}}
    v = pm.match([_inv(contact_code="VC0098765")], BOOK, ODOO, links)[0]
    assert v["rule"] == "LINK" and v["customer_no"] == "28005096535"


def test_rung_4_a_composite_code_is_a_candidate_never_an_exact_match():
    v = pm.match([_inv(contact_code="VL0010239,VC0098765")], BOOK, ODOO, {})[0]
    assert v["verdict"] == "CANDIDATE" and v["customer_no"] is None
    assert {c["customer_no"] for c in v["candidates"]} == {"28005096535", "28006083653"}
    assert all(c["rule"].startswith("COMPOSITE") for c in v["candidates"])


def test_rung_4_repairs_a_suffix_and_a_short_code_but_still_only_proposes():
    assert pm.code_parts("VL0010696,697") == ["VL0010696", "VL0010697"]
    assert pm.code_parts("VC001059") == ["VC0001059"]
    v = pm.match([_inv(contact_code="VC009876,98765")], BOOK, ODOO, {})[0]
    assert v["verdict"] == "CANDIDATE"
    assert any(c["code"] == "VC0098765" for c in v["candidates"])


def test_rung_5_a_name_is_only_ever_a_candidate():
    v = pm.match([_inv(contact_code="QO-1", customer_name="คุณ มานพ  ทดสอบ")], BOOK, ODOO, {})[0]
    assert v["verdict"] == "CANDIDATE" and v["candidates"][0]["rule"] == "NAME"
    v = pm.match([_inv(contact_code="QO-1", customer_name="Mr. Somchai")], BOOK, ODOO, {})[0]
    assert v["verdict"] == "CANDIDATE" and v["candidates"][0]["rule"] == "NAME_FIRST_WORD"


def test_nothing_matches_means_unmatched_with_no_customer_invented():
    v = pm.match([_inv(contact_code="VRC0000022", customer_name="Nobody Here")], BOOK, ODOO, {})[0]
    assert v == {"verdict": "UNMATCHED", "rule": None, "customer_no": None, "candidates": []}


def test_build_book_index_handles_object_input_with_attributes():
    # I4: Test the object-input path with SimpleNamespace
    customers = [
        types.SimpleNamespace(
            customer_no="28005096535", volt_id="28005096535_Manop_มานพ ทดสอบ_IPW",
            phone_e164="+66812345678", display_name="มานพ ทดสอบ", name_roman="Manop"
        ),
        types.SimpleNamespace(
            customer_no="28006083653", volt_id="VC0098765_Somchai_สมชาย ทำดี_SLT",
            phone_e164="+66898765432", display_name="สมชาย ทำดี", name_roman="Somchai"
        ),
    ]
    book = pm.build_book_index(customers)
    # Verify the indices were built correctly
    assert book["by_no"]["28005096535"] == "28005096535"
    assert book["by_vid"]["VC0098765"] == "28006083653"
    assert book["by_phone"]["0812345678"] == "28005096535"
    # Match through the object-built index
    v = pm.match([_inv(contact_code="VC0098765")], book, ODOO, {})[0]
    assert v["verdict"] == "EXACT" and v["customer_no"] == "28006083653"


def test_composite_with_same_customer_is_candidate():
    # I5: Composite whose parts resolve to the same customer
    v = pm.match([_inv(contact_code="VL0010239,VL0010239")], BOOK, ODOO, {})[0]
    assert v["verdict"] == "CANDIDATE" and v["customer_no"] is None


def test_lone_repaired_short_code_is_candidate():
    # I5: Lone repaired short code through match() - repairs to VC0098765
    v = pm.match([_inv(contact_code="VC98765")], BOOK, ODOO, {})[0]
    assert v["verdict"] == "CANDIDATE" and v["customer_no"] is None
    # The repaired code should be in candidates
    assert any(c["code"] == "VC0098765" for c in v["candidates"])


def test_code_parts_splits_a_space_joined_composite():
    # I1: Space-joined composites should split properly
    assert pm.code_parts("VL0010239 VC0010687") == ["VL0010239", "VC0010687"]
    assert pm.code_parts("VC 0098765") == ["VC0098765"]


def test_a_space_joined_composite_is_a_candidate():
    # I1: Space-joined composite should match as CANDIDATE
    v = pm.match([_inv(contact_code="VL0010239 VC0098765")], BOOK, ODOO, {})[0]
    assert v["verdict"] == "CANDIDATE" and v["customer_no"] is None


def test_a_suffix_is_repaired_only_from_the_adjacent_code():
    # I2: Repairs only from immediately adjacent code
    assert pm.code_parts("VC0098765,ABC,120") == ["VC0098765", "ABC", "120"]


def test_a_full_multi_word_name_is_rule_name():
    # I3: Full multi-word name (2+ words) is rule NAME
    v = pm.match([_inv(contact_code="QO-1", customer_name="คุณ มานพ  ทดสอบ")], BOOK, ODOO, {})[0]
    assert v["verdict"] == "CANDIDATE"
    assert any(c["rule"] == "NAME" and c["customer_no"] == "28005096535" for c in v["candidates"])


def test_a_first_word_hit_is_rule_name_first_word():
    # I3: First-word hit (multi-word name not in book) is rule NAME_FIRST_WORD
    v = pm.match([_inv(contact_code="QO-1", customer_name="Somchai Tamdee")], BOOK, ODOO, {})[0]
    assert v["verdict"] == "CANDIDATE"
    assert any(c["rule"] == "NAME_FIRST_WORD" and c["customer_no"] == "28006083653" for c in v["candidates"])


def test_a_bare_given_name_is_capped_like_a_first_word():
    # I3: Bare given name (one word, like "Mr. Somchai") is treated as first-word with cap
    v = pm.match([_inv(contact_code="QO-1", customer_name="Mr. Somchai")], BOOK, ODOO, {})[0]
    assert v["verdict"] == "CANDIDATE"
    assert any(c["rule"] == "NAME_FIRST_WORD" and c["customer_no"] == "28006083653" for c in v["candidates"])


def test_a_given_name_shared_by_four_customers_proposes_nothing():
    # I3: Given name shared by 4+ customers proposes nothing (ambiguous)
    idx = pm.build_book_index([
        {"customer_no": "C1", "volt_id": None, "phone_e164": None, "display_name": "Test1", "name_roman": "Somchai"},
        {"customer_no": "C2", "volt_id": None, "phone_e164": None, "display_name": "Test2", "name_roman": "Somchai"},
        {"customer_no": "C3", "volt_id": None, "phone_e164": None, "display_name": "Test3", "name_roman": "Somchai"},
        {"customer_no": "C4", "volt_id": None, "phone_e164": None, "display_name": "Test4", "name_roman": "Somchai"},
    ])
    v = pm.match([_inv(contact_code="QO-1", customer_name="Somchai Tamdee")], idx, {}, {})[0]
    assert v["verdict"] == "UNMATCHED"
    v = pm.match([_inv(contact_code="QO-1", customer_name="Mr. Somchai")], idx, {}, {})[0]
    assert v["verdict"] == "UNMATCHED"


# --- Final review I3: a V-id or a phone held by two book customers is never EXACT ---
# build_book_index mapped both last-wins, so a shared key silently auto-applied to
# whichever customer came last. A shared key now proposes every holder instead.

SHARED_BOOK = pm.build_book_index([
    {"customer_no": "28000000001", "volt_id": "VC0098765_Anong_อนงค์_IPW", "phone_e164": "+66811111111",
     "display_name": "อนงค์ หนึ่ง", "name_roman": "Anong"},
    {"customer_no": "28000000002", "volt_id": "VC0098765_Anong_อนงค์_SLT", "phone_e164": "0822222222",
     "display_name": "อนงค์ สอง", "name_roman": "Anong"},
    {"customer_no": "28000000003", "volt_id": "VL0099999_Boon_บุญ_IPW", "phone_e164": "+66822222222",
     "display_name": "บุญ สาม", "name_roman": "Boon"},
    # the same customer twice (two sources) is still ONE holder, not a shared key
    {"customer_no": "28000000004", "volt_id": "VRC0000044_Chai_ชัย_IPW", "phone_e164": "0844444444",
     "display_name": "ชัย สี่", "name_roman": "Chai"},
    {"customer_no": "28000000004", "volt_id": "VRC0000044_Chai_ชัย_IPW", "phone_e164": "0844444444",
     "display_name": "ชัย สี่", "name_roman": "Chai"},
])


def test_a_v_id_held_by_two_book_customers_is_a_candidate_naming_both_in_book_order():
    v = pm.match([_inv(contact_code="VC0098765")], SHARED_BOOK, {}, {})[0]
    assert v["verdict"] == "CANDIDATE" and v["customer_no"] is None and v["rule"] is None
    assert [c["customer_no"] for c in v["candidates"]] == ["28000000001", "28000000002"]
    assert all(c["rule"] == "SHARED_VOLT_ID" and c["code"] == "VC0098765" for c in v["candidates"])


def test_an_odoo_phone_held_by_two_book_customers_is_a_candidate_naming_both():
    odoo = pm.build_odoo_index([{"volt_id": "VL0010239", "phone_e164": "0822222222"}])
    v = pm.match([_inv(contact_code="VL0010239")], SHARED_BOOK, odoo, {})[0]
    assert v["verdict"] == "CANDIDATE" and v["customer_no"] is None
    assert [c["customer_no"] for c in v["candidates"]] == ["28000000002", "28000000003"]
    assert all(c["rule"] == "SHARED_PHONE" for c in v["candidates"])


def test_a_key_the_same_customer_holds_twice_is_still_exact():
    v = pm.match([_inv(contact_code="VRC0000044")], SHARED_BOOK, {}, {})[0]
    assert v == {"verdict": "EXACT", "rule": "VOLT_ID", "customer_no": "28000000004", "candidates": []}


def test_a_shared_v_id_is_never_rescued_by_a_later_exact_column():
    # the contact code is ambiguous; the reference's own exact hit is proposed beside
    # the two holders, never applied over them.
    v = pm.match([_inv(contact_code="VC0098765", reference="28000000003")], SHARED_BOOK, {}, {})[0]
    assert v["verdict"] == "CANDIDATE"
    assert [c["customer_no"] for c in v["candidates"]] == ["28000000001", "28000000002", "28000000003"]


def test_a_composite_part_with_a_shared_v_id_proposes_every_holder():
    v = pm.match([_inv(contact_code="VC0098765,VL0099999")], SHARED_BOOK, {}, {})[0]
    assert v["verdict"] == "CANDIDATE"
    assert [c["customer_no"] for c in v["candidates"]] == ["28000000001", "28000000002", "28000000003"]
    assert [c["rule"] for c in v["candidates"]] == ["COMPOSITE:SHARED_VOLT_ID", "COMPOSITE:SHARED_VOLT_ID",
                                                    "COMPOSITE:VOLT_ID"]


# --- feedback round 2 / TASK-211: honourifics and the cross-script rung (ADDITIONS) --

def test_honorifics_are_stripped_before_the_name_rungs():
    assert pm.normalise_name("คุณ วรารัตน์  แสงทอง") == "วรารัตน์ แสงทอง"
    assert pm.normalise_name("Mr. Worarut Sangtong") == "worarut sangtong"
    assert pm.normalise_name("ด.ช. เอ บี") == "เอ บี"


def test_a_cross_script_name_is_a_candidate_never_exact():
    book = pm.build_book_index([
        {"customer_no": "28007000001", "volt_id": "VL0000001_x",
         "display_name": "วรารัตน์ แสงทอง", "name_roman": "Worarut Sangtong"},
    ])
    v = pm.match([_inv(contact_code="QO-9", customer_name="Worarut Sangtong")], book, {}, {})[0]
    assert v["verdict"] == "CANDIDATE" and v["customer_no"] is None
    assert any(c["rule"] == "NAME_XSCRIPT" and c["customer_no"] == "28007000001" for c in v["candidates"])


def test_a_thai_name_hit_stays_name_not_xscript():
    v = pm.match([_inv(contact_code="QO-10", customer_name="คุณ มานพ ทดสอบ")], BOOK, ODOO, {})[0]
    assert any(c["rule"] == "NAME" for c in v["candidates"])
