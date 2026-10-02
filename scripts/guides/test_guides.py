"""The guide stays true to the code, and the committed copy carries no password."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import role_matrix  # noqa: E402


@pytest.mark.parametrize("row", role_matrix.ROWS, ids=lambda r: "%s:%s" % (r[5], r[6]))
def test_every_citation_still_says_what_the_guide_says(row):
    *_text, allowed, file, line, needle = row
    assert needle != "NEEDLE", "fill the needle for %s:%s" % (file, line)
    assert set(allowed) <= set(role_matrix.ROLES)
    lines = (ROOT / file).read_text(encoding="utf-8").splitlines()
    window = "\n".join(lines[max(0, line - 4): line + 3])
    assert needle in window, "%s:%s no longer contains %r" % (file, line, needle)


def test_the_repo_build_has_no_password(tmp_path):
    fake = tmp_path / "accounts.json"
    fake.write_text(json.dumps({u: "PW-%s-SECRET" % u for u in
                                ["tester", "officer.test", "supervisor.test", "manager.test", "owner.test", "ops.test"]}))
    out = tmp_path / "repo.docx"
    subprocess.run([sys.executable, str(HERE / "build_login_guide.py"), "--accounts", str(fake),
                    "--repo-out", str(out), "--vault-out", str(tmp_path / "vault.docx")], check=True)
    import zipfile
    repo_xml = zipfile.ZipFile(out).read("word/document.xml").decode("utf-8")
    vault_xml = zipfile.ZipFile(tmp_path / "vault.docx").read("word/document.xml").decode("utf-8")
    assert "SECRET" not in repo_xml
    assert "PW-manager.test-SECRET" in vault_xml
