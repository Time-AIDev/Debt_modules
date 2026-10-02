import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location("release", Path(__file__).resolve().parents[2] / "infra/production/release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def test_missing_evidence_cannot_promote(tmp_path):
    path = tmp_path / "gates.json"
    path.write_text(json.dumps({"project": "volt-debt-prd", "images": {}}))
    with pytest.raises(ValueError, match="backend"):
        release.verify_gates(path, {"project": "volt-debt-prd", "images": {}})


def test_staging_project_and_mutable_image_tags_are_refused(tmp_path):
    with pytest.raises(ValueError): release.project("dept-collection-508109")
    path = tmp_path / "release.json"
    path.write_text(json.dumps({"project": "volt-debt-prd", "revision": "a" * 40,
                                "images": {"api": "asia-southeast1-docker.pkg.dev/volt-debt-prd/debt/api:latest"}}))
    with pytest.raises(ValueError): release.load_release(path)
