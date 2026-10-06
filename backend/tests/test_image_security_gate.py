"""Fixable Go and OS vulnerabilities must block the same image release gate."""
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('image_security_gate_review', ROOT/'scripts/image_security_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def report(tmp_path, vulnerabilities):
    path = tmp_path/'trivy.json'
    path.write_text(json.dumps({'ArtifactType': 'container_image',
        'Metadata': {'ImageID': 'sha256:'+'a'*64},
        'Results': [{'Target': 'usr/local/bin/gosu', 'Vulnerabilities': vulnerabilities}]}))
    return path


def test_go_standard_library_is_not_exempted_from_release_gate(tmp_path):
    result = gate.inspect(report(tmp_path, [{'VulnerabilityID': 'CVE-synthetic', 'PkgName': 'stdlib',
        'InstalledVersion': 'v1.24.6', 'FixedVersion': '1.27.1', 'Severity': 'CRITICAL'}]))
    assert not result['passed']
    assert result['fixable_high_critical'][0]['PkgName'] == 'stdlib'


def test_unfixed_findings_remain_visible_and_fixed_lower_severity_does_not_block(tmp_path):
    result = gate.inspect(report(tmp_path, [
        {'VulnerabilityID': 'CVE-unfixed', 'PkgName': 'package', 'Severity': 'HIGH'},
        {'VulnerabilityID': 'CVE-medium', 'PkgName': 'package', 'Severity': 'MEDIUM', 'FixedVersion': '2'}]))
    assert result['passed'] and len(result['unfixed_high_critical']) == 1


def test_missing_image_scan_evidence_refuses_instead_of_passing(tmp_path):
    path = tmp_path/'empty.json'
    path.write_text('{}')
    with pytest.raises(ValueError):
        gate.inspect(path)
