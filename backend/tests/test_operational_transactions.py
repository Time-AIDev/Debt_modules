"""Only the proved PEAK raw-file enqueue branches may skip portfolio locking."""
import pytest

from app.operational_transactions import is_peak_enqueue, PEAK_STARTS


def scope(path="/v1/pipelines/peak-report:start", method="POST", content_type=b"application/octet-stream", **fields):
    return {"type": "http", "path": path, "method": method, "query_string": b"",
            "headers": [] if content_type is None else [(b"content-type", content_type)], **fields}


@pytest.mark.parametrize("path", sorted(PEAK_STARTS))
@pytest.mark.parametrize("content_type", [None, b"application/octet-stream", b"text/csv",
                                        b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"])
def test_raw_file_submission_is_operational(path, content_type):
    assert is_peak_enqueue(scope(path, content_type=content_type))


@pytest.mark.parametrize("content_type", [b"application/json", b"Application/JSON; charset=utf-8",
                                        b"application/vnd.peak+json", b"text/json"])
@pytest.mark.parametrize("path", sorted(PEAK_STARTS))
def test_api_or_json_door_stays_global(path, content_type):
    assert not is_peak_enqueue(scope(path, content_type=content_type))


@pytest.mark.parametrize("path", sorted(PEAK_STARTS))
def test_worker_execution_stays_global_even_when_it_reuses_the_start_route(path):
    assert not is_peak_enqueue(scope(path, volt_worker=True))
    assert not is_peak_enqueue(scope(path), worker_run=True)


@pytest.mark.parametrize("path", ["/v1/pipelines/peak-report:run", "/v1/pipelines/peak-receipt:run",
    "/v1/pipelines/peak-report/landing-runs/1:apply", "/v1/pipelines/peak-receipt/landing-runs/1:apply",
    "/v1/pipelines/peak-report/links", "/v1/pipelines/crm-lead:start", "/v1/pipelines/peak-report:start/",
    "/v1/pipelines/peak-report:start/unknown"])
def test_parsing_matching_application_and_other_routes_stay_global(path):
    assert not is_peak_enqueue(scope(path))


@pytest.mark.parametrize("method", ["GET", "HEAD", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_unproved_methods_stay_global(method):
    assert not is_peak_enqueue(scope(method=method))


def test_unknown_query_and_duplicate_selector_headers_stay_global():
    assert not is_peak_enqueue(scope(query_string=b"install=true"))
    assert not is_peak_enqueue(scope(headers=[(b"content-type", b"application/octet-stream"),
                                            (b"content-type", b"application/json")]))
    assert not is_peak_enqueue(scope(headers=[(b"content-type", b"application/octet-stream"),
                                            (b"content-type", b"application/octet-stream")]))
