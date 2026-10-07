"""Incident retries keep identity and acknowledge failures/recoveries honestly."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


DIRECTORY = Path(__file__).resolve().parents[2] / "infra/vps"
spec = importlib.util.spec_from_file_location("incident_delivery_test", DIRECTORY / "incident_alerts.py")
alerts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alerts)
NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)


class Response:
    status = 204
    def __enter__(self): return self
    def __exit__(self, *args): return None
    def read(self, limit): return b""


class Receiver:
    def __init__(self, failures=0):
        self.failures, self.requests = failures, []
    def open(self, request, timeout):
        self.requests.append(request)
        if self.failures:
            self.failures -= 1
            raise OSError("synthetic connection failure")
        return Response()


def settings():
    return {"url": "https://receiver.example.test/events", "token": "unit-only-token",
            "environment": "staging", "service": "volt-debt"}


def test_delivery_retries_use_same_event_and_deduplicate_acknowledged_failure(tmp_path):
    receiver = Receiver(failures=2)
    path = tmp_path / "state.json"
    result = alerts.publish(["worker heartbeat failed"], settings(), path,
                            opener=receiver, now=NOW, sleeper=lambda n: None)
    assert result["acknowledged"] is True and result["state"] == "failure"
    ids = [request.get_header("Idempotency-key") for request in receiver.requests]
    assert len(ids) == 3 and len(set(ids)) == 1
    assert path.stat().st_mode & 0o777 == 0o600
    again = alerts.publish(["worker heartbeat failed"], settings(), path,
                           opener=receiver, now=NOW + timedelta(minutes=1))
    assert again["deduplicated"] is True and len(receiver.requests) == 3
    assert "unit-only-token" not in path.read_text()


def test_failed_delivery_retains_pending_id_for_later_retry_and_recovery(tmp_path):
    path = tmp_path / "state.json"
    receiver = Receiver(failures=3)
    with pytest.raises(alerts.AlertError, match="pending"):
        alerts.publish(["API readiness failed"], settings(), path, opener=receiver,
                       now=NOW, sleeper=lambda n: None)
    pending = json.loads(path.read_text())["pending"]["event_id"]
    result = alerts.publish(["API readiness failed"], settings(), path, opener=receiver,
                            now=NOW + timedelta(seconds=60))
    assert result["event_id"] == pending
    recovery = alerts.publish([], settings(), path, opener=receiver,
                              now=NOW + timedelta(seconds=120))
    assert recovery["state"] == "recovery" and recovery["event_id"] != pending
    assert json.loads(receiver.requests[-1].data)["summary"] == "Operational checks recovered"


def test_uncertain_failure_is_followed_by_recovery_even_without_failure_ack(tmp_path):
    path = tmp_path / "state.json"
    with pytest.raises(alerts.AlertError):
        alerts.publish(["database unavailable"], settings(), path, opener=Receiver(3),
                       now=NOW, sleeper=lambda n: None)
    assert alerts.publish([], settings(), path, opener=Receiver(),
                          now=NOW + timedelta(minutes=1))["state"] == "recovery"


def test_no_configuration_never_claims_delivery(tmp_path):
    result = alerts.publish([], {}, tmp_path / "state.json", now=NOW)
    assert result == {"configured": False, "acknowledged": False}
    assert not (tmp_path / "state.json").exists()


@pytest.mark.parametrize("change", [{"url": "http://receiver.example.test/events"},
                                   {"url": "https://user:password@receiver.example.test/events"},
                                   {"token": "header\ninvalid"}])
def test_receiver_configuration_rejects_unsafe_transport_and_auth(tmp_path, change):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({**settings(), **change}))
    path.chmod(0o600)
    with pytest.raises(alerts.AlertError):
        alerts.config(path)


def test_public_configuration_and_symlink_state_are_rejected(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(settings()))
    path.chmod(0o644)
    with pytest.raises(alerts.AlertError, match="permissions"):
        alerts.config(path)
    path.chmod(0o600)
    link = tmp_path / "state.json"
    link.symlink_to(path)
    with pytest.raises(alerts.AlertError):
        alerts.publish([], settings(), link, now=NOW, opener=Receiver())


def test_external_watchdog_refuses_production_and_checks_rpo(monkeypatch):
    spec = importlib.util.spec_from_file_location("external_watchdog_test", DIRECTORY / "external-watchdog.py")
    watchdog = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(watchdog)
    monkeypatch.setattr(watchdog, "machine_fingerprint", lambda: "a"*64)
    config = {"production_fingerprint": "a"*64, "recovery_point_remote": "offsite:latest.json"}
    with pytest.raises(ValueError, match="independent"):
        watchdog.inspect(config, now=NOW)
    monkeypatch.setattr(watchdog, "machine_fingerprint", lambda: "b"*64)
    class Ready(Response):
        status = 200
        def read(self, limit): return b'{"status":"ready"}'
    class Probe:
        def open(self, url, timeout): return Ready()
    def storage(*args, **kwargs):
        return SimpleNamespace(stdout=json.dumps({"encrypted": True,
            "captured_at_utc": (NOW - timedelta(hours=25)).isoformat()}))
    assert watchdog.inspect(config, now=NOW, opener=Probe(), command=storage) == [
        "encrypted offsite recovery point exceeds 24-hour RPO"]
    with pytest.raises(ValueError, match='fingerprint'):
        watchdog.inspect({**config, 'production_fingerprint': ''}, now=NOW)


@pytest.fixture
def independent_watchdog(monkeypatch):
    spec = importlib.util.spec_from_file_location("watchdog_deferral_test", DIRECTORY / "external-watchdog.py")
    watchdog = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(watchdog)
    monkeypatch.setattr(watchdog, "machine_fingerprint", lambda: "b" * 64)
    return watchdog


def test_watchdog_deferred_offsite_still_checks_https_and_never_runs_storage(independent_watchdog):
    watchdog = independent_watchdog
    calls = []
    class Ready(Response):
        status = 200
        def read(self, limit): return b'{"status":"ready"}'
    class Probe:
        def open(self, url, timeout):
            calls.append(url)
            return Ready()
    settings = {"production_fingerprint": "a" * 64, "offsite_monitoring": "deferred"}
    def no_storage(*args, **kwargs):
        pytest.fail("Explicit offsite deferral must not invoke rclone")
    assert watchdog.inspect(settings, now=NOW, opener=Probe(), command=no_storage) == []
    assert calls == ["https://collection.volt.co.th/readyz"]
    class Unreachable:
        def open(self, url, timeout): raise OSError("unreachable")
    assert watchdog.inspect(settings, now=NOW, opener=Unreachable(), command=no_storage) == [
        "production public HTTPS unreachable or not ready"]


def test_watchdog_configuration_defers_only_storage_not_receiver_or_independence(tmp_path, independent_watchdog):
    watchdog = independent_watchdog
    receiver = tmp_path / "alerts.json"
    receiver.write_text(json.dumps(settings()))
    receiver.chmod(0o600)
    path = tmp_path / "watchdog.json"
    config = {"production_fingerprint": "a" * 64, "offsite_monitoring": "deferred",
              "alerts_config": str(receiver), "state_path": str(tmp_path / "state.json")}
    def save(value):
        path.write_text(json.dumps(value))
        path.chmod(0o600)
    save(config)
    assert watchdog.configuration(path)["offsite_monitoring"] == "deferred"
    save({key: value for key, value in config.items() if key != "offsite_monitoring"})
    with pytest.raises(ValueError, match="offsite recovery point"):
        watchdog.configuration(path)
    save({**config, "production_fingerprint": "b" * 64})
    with pytest.raises(ValueError, match="independent"):
        watchdog.configuration(path)
    save(config)
    receiver.write_text(json.dumps({"url": "", "token": ""}))
    with pytest.raises(watchdog.AlertError):
        watchdog.configuration(path)


@pytest.mark.parametrize("mode", ["", "disabled", "optional", False, None])
def test_unknown_watchdog_offsite_mode_fails_closed(independent_watchdog, mode):
    watchdog = independent_watchdog
    class NoProbe:
        def open(self, *args, **kwargs): pytest.fail("Invalid policy must fail before probing")
    with pytest.raises(ValueError, match="explicitly deferred"):
        watchdog.inspect({"production_fingerprint": "a" * 64, "offsite_monitoring": mode},
                         now=NOW, opener=NoProbe())
