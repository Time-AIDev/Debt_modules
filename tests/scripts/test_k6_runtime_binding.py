"""Load evidence binds an isolated image without reading container credentials."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("k6_runner", ROOT / "scripts/run_k6.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@pytest.mark.parametrize("revision, expected", [("a" * 40, "a" * 40), ("a" * 40 + "-dirty", None)])
def test_binding_reads_only_image_and_revision(monkeypatch, revision, expected):
    def inspect(args, **kwargs):
        assert args[:3] == ["docker", "inspect", "--format"]
        assert args[-1] == "owned-load-api" and ".Config.Env" not in args[3]
        return SimpleNamespace(stdout=json.dumps({"image": "sha256:" + "b" * 64, "revision": revision,
                                                 "unknown_secret": "PRIVATE-TOKEN"}))
    monkeypatch.setattr(runner.subprocess, "run", inspect)
    value = runner.runtime_binding("owned-load-api")
    assert value == {"api_image": "sha256:" + "b" * 64, "revision": expected}
    assert "PRIVATE-TOKEN" not in json.dumps(value)


def test_missing_container_does_not_claim_source_binding():
    assert runner.runtime_binding(None) == {}


def test_nonimmutable_image_is_refused(monkeypatch):
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        stdout=json.dumps({"image": "latest", "revision": "a" * 40})))
    with pytest.raises(ValueError):
        runner.runtime_binding("owned-load-api")
