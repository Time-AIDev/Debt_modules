import pytest
from app.attachments import scanner


def test_production_refuses_unconfigured_scanner(monkeypatch):
    monkeypatch.setenv("ENV", "prd")
    monkeypatch.delenv("SCANNER_URL", raising=False)
    monkeypatch.delenv("CLAMAV_HOST", raising=False)
    with pytest.raises(scanner.ScannerUnavailable):
        scanner.scan(b"file")


def test_http_scanner_uses_workload_identity_and_refuses_infection(monkeypatch):
    monkeypatch.setenv("SCANNER_URL", "https://scanner.example")
    calls = []
    monkeypatch.setattr(scanner, "identity_token", lambda audience: "workload-token", raising=False)
    class Response:
        status_code = 422
        def json(self): return {"signature": "EICAR"}
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    monkeypatch.setattr("requests.post", post)
    with pytest.raises(scanner.Infected): scanner.scan(b"file")
    assert calls[0][1]["headers"]["Authorization"] == "Bearer workload-token"
    assert calls[0][1]["data"] == b"file"

