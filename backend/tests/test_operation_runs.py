import pytest
from fastapi.testclient import TestClient

from app import imports as imports_domain
from app.main import app
from app.pipelines import runs
from app.routers import imports as imports_router


@pytest.fixture(autouse=True)
def clean_runs():
    runs.reset()
    yield
    runs.reset()


@pytest.fixture
def client():
    return TestClient(app)


def test_operation_run_uses_the_shared_phase_state_machine():
    uid = runs.start("master_sheet", total_bytes=100)
    assert runs.get(uid)["state"] == "queued"

    runs.progress(uid, phase="uploading", uploaded_bytes=40)
    assert runs.get(uid)["state"] == "uploading"
    runs.progress(uid, phase="parsing", processed=3, phase_total=10)
    assert runs.get(uid)["state"] == "parsing"
    runs.progress(uid, phase="scanning")
    assert runs.get(uid)["state"] == "scanning"
    runs.progress(uid, phase="applying")
    assert runs.get(uid)["state"] == "applying"


def test_cancel_is_cooperative_before_commit_and_refused_after_commit():
    uid = runs.start("assignment")
    cancelled = runs.cancel(uid)
    assert cancelled["state"] == "cancel_requested"

    with pytest.raises(runs.RunCancelled):
        runs.checkpoint(uid)
    assert runs.get(uid)["state"] == "cancelled"

    committed = runs.start("attachment")
    runs.mark_committed(committed)
    with pytest.raises(runs.RunNotCancellable):
        runs.cancel(committed)


@pytest.mark.parametrize("phase", ["uploading", "parsing", "scanning", "applying"])
def test_every_pre_commit_phase_honours_cancellation(phase):
    uid = runs.start("upload")
    runs.progress(uid, phase=phase)
    runs.cancel(uid)
    with pytest.raises(runs.RunCancelled):
        runs.checkpoint(uid)
    assert runs.get(uid)["state"] == "cancelled"


def test_cancelling_a_terminal_run_is_refused():
    uid = runs.start("peak_invoice")
    runs.finish(uid, {"landed": 2})

    with pytest.raises(runs.RunNotCancellable):
        runs.cancel(uid)


def test_operation_run_http_surface(client):
    uid = runs.start("master_sheet")

    assert client.get(f"/v1/operation-runs/{uid}").json()["state"] == "queued"
    stopped = client.post(f"/v1/operation-runs/{uid}:cancel")
    assert stopped.status_code == 200
    assert stopped.json()["state"] == "cancel_requested"

    runs.checkpoint(uid, raise_cancelled=False)
    refused = client.post(f"/v1/operation-runs/{uid}:cancel")
    assert refused.status_code == 409
    assert refused.json()["code"] == "run_not_cancellable"


def test_upload_parts_can_be_cleaned_up_on_abort():
    upload_id = "00000000-0000-4000-8000-000000000001"
    imports_domain.put_part(upload_id, 0, 2, b"abc", "officer")

    assert imports_domain.discard_upload(upload_id, "officer") is True
    assert imports_domain.discard_upload(upload_id, "officer") is False


def test_cancelled_master_run_removes_the_parsed_preview(monkeypatch):
    operation_uid = runs.start("master-sheet")
    import_uid = "imp-cancelled-preview"
    import_state = imports_domain.for_current()

    def fake_parse(*_args, **_kwargs):
        preview = {"run": {"uid": import_uid}}
        import_state.runs[import_uid] = preview
        runs.cancel(operation_uid)
        return preview, {"customers": []}

    monkeypatch.setattr(imports_domain, "parse_upload", fake_parse)
    monkeypatch.setattr(imports_router.db, "configured", lambda: True)

    with pytest.raises(runs.RunCancelled):
        imports_router._process_import(
            b"data", "master.csv", "officer", "MANAGER", False, None,
            operation_uid,
        )

    assert import_uid not in import_state.runs
