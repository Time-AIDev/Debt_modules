"""Revision evidence must fail when source changes or undeclared code is present."""
import importlib.util
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('dataflow_binding', ROOT / 'scripts/test_dataflow.py')
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def git(root, *args):
    subprocess.run(['git', *args], cwd=root, capture_output=True, check=True)


def test_run_proof_rejects_edits_commits_and_untracked_code_without_exposing_content(tmp_path):
    git(tmp_path, 'init')
    git(tmp_path, 'config', 'user.email', 'synthetic@example.test')
    git(tmp_path, 'config', 'user.name', 'Synthetic Test')
    source = tmp_path / 'backend/app'
    source.mkdir(parents=True)
    code = source / 'sample.py'
    code.write_text('VALUE = "PRIVATE-CONTENT"\n')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-m', 'Synthetic baseline')
    before = runner.source_manifest(tmp_path)
    assert runner.source_unchanged(before, runner.source_manifest(tmp_path))
    assert 'PRIVATE-CONTENT' not in str(before)
    (tmp_path / 'reports').mkdir()
    (tmp_path / 'reports/output.docx').write_bytes(b'aggregate')
    assert runner.source_unchanged(before, runner.source_manifest(tmp_path))
    extra = source / 'undeclared.py'
    extra.write_text('NEW = True\n')
    assert not runner.source_unchanged(before, runner.source_manifest(tmp_path))
    extra.unlink()
    code.write_text('VALUE = "CHANGED"\n')
    assert not runner.source_unchanged(before, runner.source_manifest(tmp_path))
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-m', 'Synthetic source change')
    assert not runner.source_unchanged(before, runner.source_manifest(tmp_path))


def test_missing_git_context_never_certifies_revision(tmp_path):
    missing = runner.source_manifest(tmp_path)
    assert missing['revision'] is None
    assert not runner.source_unchanged(missing, missing)
