"""Language pass: the pipeline, payments and clock display strings carry English twins —
present, non-empty, no Thai script (฿ is a currency sign), no internal codes."""
import re
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app import clock
from app import peak_documents as pkd
from app.config import settings
from app.main import app

from tests.test_no_codes_in_prose import CODE

THAI = re.compile(r"[฀-฾เ-๿]")


def english(text):
    assert isinstance(text, str) and text.strip(), text
    assert not THAI.search(text), text
    assert not CODE.search(text), text


def _items(client):
    return client.get("/v1/pipeline", params={"all": True}).json()


def test_pipeline_list_notes_have_english_twins():
    client = TestClient(app)
    body = _items(client)
    counts = body["meta"]["counts"]
    english(counts["counts_note_en"])
    if counts.get("beyond_note_th"):
        english(counts["beyond_note_en"])
    hinted = [i for i in body["items"] if i.get("amount_hint_note_th")]
    assert hinted, "the fixture book carries an amount hint"
    for i in hinted:
        english(i["amount_hint_note_en"])


def test_pipeline_marker_notes_have_english_twins():
    client = TestClient(app)
    items = [i for i in _items(client)["items"] if not i.get("released_at")]
    far = str(settings.business_date + timedelta(days=400))
    moved = client.post("/v1/pipeline/%s/install-outcome" % items[0]["uid"],
                        json={"outcome": "POSTPONED", "new_install_on": far}).json()["item"]
    english(moved["moved_note_en"])
    installed = client.post("/v1/pipeline/%s/install-outcome" % items[1]["uid"],
                            json={"outcome": "INSTALLED"}).json()["item"]
    english(installed["installed_uninvoiced_note_en"])


def test_peak_transport_note_and_local_stamp_are_english():
    pkd.TRANSPORT_OVERRIDE = pkd.StubTransport()
    try:
        english(TestClient(app).get("/v1/peak-documents").json()["meta"]["transport_note_en"])
    finally:
        pkd.TRANSPORT_OVERRIDE = None
    english(clock.local_stamp_en(datetime(2026, 9, 2, 2, 12, tzinfo=timezone.utc)))
