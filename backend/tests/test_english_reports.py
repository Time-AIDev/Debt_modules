"""Language pass (README step 7): every Thai display string the Reports and Overview
screens read has an English twin — present, non-empty, no Thai script, no internal codes."""
import re

from fastapi.testclient import TestClient

from app import collection_kpi
from app.main import app
from tests.test_no_codes_in_prose import CODE

THAI = re.compile(r"[฀-฾เ-๿]")   # ฿ (U+0E3F) is a currency sign
MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}
SCREENS = ("/v1/reports/weekly", "/v1/reports/collection?measure=due_month",
           "/v1/reports/collection?measure=cash_received", "/v1/reports/bucket-flow", "/v1/reports/team")


def _twins(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            if k.endswith("_th") and isinstance(v, str):
                yield path + k, node.get(k[:-3] + "_en")
            yield from _twins(v, path + k + ".")
    elif isinstance(node, list):
        for v in node:
            yield from _twins(v, path)


def _english(text, where):
    assert isinstance(text, str) and text.strip(), where
    assert not THAI.search(text), (where, text)
    assert not CODE.search(text), (where, text)


def test_every_served_thai_display_string_has_an_english_twin():
    c = TestClient(app)
    c.cookies.set("volt_session", "english-reports")
    for url in SCREENS:
        body = c.get(url, headers=MANAGER).json()
        pairs = list(_twins(body))
        assert pairs, url
        for where, en in pairs:
            _english(en, url + " " + where)


def test_constant_and_composed_twins():
    for text in (collection_kpi.TEAM_NOTE_EN, collection_kpi.CONTRACTS_NOTE_EN,
                 collection_kpi.CLOSING_UNCOMPUTABLE_NOTE_EN, *collection_kpi.MEASURE_LABEL_EN.values(),
                 ):
        _english(text, text)
    for key in ("contact_rate:portfolio", "due_month:team", "nope:portfolio", "due_month:x"):
        ok, _code, (th, en) = collection_kpi.validate_target_key(key)
        assert not ok and THAI.search(th) and en != th
        _english(en, key)
    assert "<measure>:portfolio" in collection_kpi.validate_target_key("due_month:x")[2][1]
    for raw in (None, "400,000", "Infinity"):
        ok, _v, (th, en) = collection_kpi.validate_target_value(raw)
        assert not ok and THAI.search(th)
        _english(en, raw)
    for target in (None, "0"):
        _pct, th, en, _bar = collection_kpi._attainment("5", target)
        assert THAI.search(th)
        _english(en, target)
    assert collection_kpi._attainment("5", "100")[1:3] == (None, None)
    from datetime import date
    for ym in ((2026, 10), (2026, 9), (2026, 11)):
        _english(collection_kpi._month_progress_note_en(*ym, date(2026, 10, 23)), ym)
    _english(collection_kpi._month_progress_note_en(2026, 10, date(2026, 10, 31)), "last day")


def test_a_refused_target_names_its_field_in_english():
    c = TestClient(app)
    c.cookies.set("volt_session", "english-reports-target")
    r = c.put("/v1/reports/collection/2026-10/targets", headers=MANAGER,
              json={"due_month:portfolio": "400,000", "contact_rate:portfolio": "1"})
    assert r.status_code == 422, r.json()
    for e in r.json()["errors"]:
        _english(e["message"], e["pointer"])
        assert THAI.search(e["message_th"])
