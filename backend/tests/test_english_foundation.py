"""Language pass: the shared English twins (ladder acts, band labels) — present, English, code-free."""
import re

from app import ladder
from app.money import band_sets
from tests.test_no_codes_in_prose import CODE

THAI = re.compile(r"[฀-฾เ-๿]")


def _english(text):
    assert text and not THAI.search(text) and not CODE.search(text), text


def test_every_ladder_rung_has_an_english_act():
    for rungs in ladder.LADDERS.values():
        for rung in rungs:
            _english(rung["act_en"])
    for step in ladder.ladder_payload("LEASE", None, 95, 3)["steps"]:
        _english(step["act_en"])
    for rung in ladder.ladder_rungs():
        _english(rung["act_en"])


def test_band_sets_serve_english_labels():
    for row in band_sets.describe():
        _english(row["label_en"])
        _english(row["reason_en"])
        for band in row["bands"]:
            _english(band["label_en"])
    for code in ("NPL_CONFIRMED", "RESOLVED", "CLOSED", "RISK_REVIEW"):
        _english(band_sets.label_for("OPERATIONAL", code, "en"))
    assert band_sets.band_label_en("X", "S4_MID", 8, 29) == "8–29 days overdue"
