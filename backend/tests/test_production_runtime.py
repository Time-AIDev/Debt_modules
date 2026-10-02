import pytest
from fastapi.testclient import TestClient
from app.main import app


def test_production_refuses_missing_database():
    from app.production_runtime import validate_environment
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        validate_environment({"ENV": "prd"})


def test_production_refuses_test_login_or_pinned_demo_date():
    from app.production_runtime import validate_environment
    settings = {"ENV": "prd", "DATABASE_URL": "postgresql+psycopg://example/debt",
                "AUTH_MODE": "on", "AUTH_SESSION_POLICY": "tab", "GOOGLE_CLIENT_ID": "google-client",
                "AUTH_ALLOW_TEST_ACCOUNTS": "false", "PEAK_OUTBOUND_ENABLED": "false"}
    validate_environment(settings)
    for key, value in (("AUTH_ALLOW_TEST_ACCOUNTS", "true"), ("VOLT_BUSINESS_DATE", "2026-10-23"),
                       ("PEAK_OUTBOUND_ENABLED", "true"), ("AUTH_MODE", "off")):
        with pytest.raises(RuntimeError):
            validate_environment(dict(settings, **{key: value}))


def test_production_readiness_fails_when_database_unavailable(monkeypatch):
    monkeypatch.setenv("ENV", "prd")
    monkeypatch.setattr("app.db.connect", lambda: (_ for _ in ()).throw(RuntimeError("secret-driver-text")))
    response = TestClient(app).get("/readyz")
    assert response.status_code == 503
    assert "secret-driver-text" not in response.text


def test_production_peak_outbound_is_disabled(monkeypatch):
    from app.integrations import peak
    monkeypatch.setenv("ENV", "prd")
    with pytest.raises(Exception) as failure:
        peak.create_draft({"intent": "test"})
    assert getattr(failure.value, "code", None) == "feature_disabled"
