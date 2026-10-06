"""Pinned content IDs also require a matching source revision for promotion."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("label", [None, "unknown", "b" * 40])
def test_candidate_image_without_exact_revision_label_is_refused(tmp_path, monkeypatch, label):
    source = Path(__file__).resolve().parents[2] / "infra/vps/release.py"
    spec = importlib.util.spec_from_file_location("release_image_label_gate", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args = SimpleNamespace(api_image="sha256:" + "1" * 64, web_image="sha256:" + "2" * 64,
                           revision="a" * 40, evidence=tmp_path / "release.json", go_live=False,
                           rollback_api_image=None, db_image=None, scanner_image=None, edge_image=None)
    release = module.Release(args)
    raw = b"GOOGLE_CLIENT_ID=synthetic\nAUTH_ALLOWLIST={}\nDATABASE_URL=postgresql://synthetic\n"
    monkeypatch.setattr(module, "ensure_directory", lambda *_a, **_kw: None)
    monkeypatch.setattr(module, "read_private", lambda *_a, **_kw: raw)
    monkeypatch.setattr(release, "source_evidence", lambda: {"commit": args.revision})
    monkeypatch.setattr(release, "verified_backup", lambda: {"restore_status": "passed"})
    monkeypatch.setattr(release, "inspect_image", lambda image: {
        "id": image, "repo_digests": [], "revision_label": label if image == args.api_image else args.revision})
    with pytest.raises(module.ReleaseError, match="exact requested Git revision"):
        release.preflight()
