"""Anonymous login-page visibility cannot approve a production go-live."""
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def gate(tmp_path):
    source = Path(__file__).resolve().parents[2] / "infra/vps/release.py"
    spec = importlib.util.spec_from_file_location("browser_release_gate", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args = SimpleNamespace(revision="a" * 40, api_image="sha256:" + "1" * 64,
                           web_image="sha256:" + "2" * 64, go_live=True,
                           browser_evidence=tmp_path / "browser.json")
    return module, module.Release(args)


def _evidence(module, release, **changes):
    data = {"target": "https://collection.volt.co.th", "status": 200,
            "google_origin_denied": False, "page_error_count": 0, "failed_requests": [],
            "browser_login_performed": True, "authenticated_google_session": True,
            "authenticated_session_kind": "GOOGLE", "revision": release.args.revision,
            "timestamp": module.utc_now().isoformat(), **changes}
    release.args.browser_evidence.write_text(json.dumps(data))


def test_recent_actual_google_browser_authentication_can_satisfy_gate(gate):
    module, release = gate
    _evidence(module, release)
    release.verify_browser_origin()
    assert release.evidence["checks"]["browser_origin"]["human_login_performed"] is True


@pytest.mark.parametrize("change", [
    {"browser_login_performed": False, "authenticated_google_session": False, "login_visible": True},
    {"authenticated_session_kind": "TEST_ACCOUNT"},
    {"google_origin_denied": True},
    {"page_error_count": 1},
    {"failed_requests": [{"origin": "https://accounts.google.com", "error": "blocked"}]},
    {"revision": "b" * 40},
    {"target": "https://other.example.test"},
])
def test_incomplete_or_mismatched_browser_evidence_cannot_promote(gate, change):
    module, release = gate
    _evidence(module, release, **change)
    with pytest.raises(module.ReleaseError):
        release.verify_browser_origin()


def test_stale_positive_browser_evidence_cannot_promote(gate):
    module, release = gate
    _evidence(module, release, timestamp=(module.utc_now() - timedelta(hours=2)).isoformat())
    with pytest.raises(module.ReleaseError, match="stale"):
        release.verify_browser_origin()
