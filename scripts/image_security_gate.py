#!/usr/bin/env python3
"""Fail a release when a Trivy image report retains fixable HIGH/CRITICAL CVEs.

Go standard-library findings receive the same gate as OS and other dependencies.
Unfixed findings are reported explicitly; no vulnerability IDs are ignored here.
"""
import argparse
import json
from pathlib import Path
import re


def inspect(path):
    report = json.loads(Path(path).read_text())
    image = report.get('Metadata', {}).get('ImageID', '')
    if (report.get('ArtifactType') != 'container_image' or
            not re.fullmatch(r'sha256:[a-f0-9]{64}', image) or not isinstance(report.get('Results'), list)):
        raise ValueError('A complete Trivy container-image report with an image digest is required')
    fixed, unfixed = [], []
    for result in report['Results']:
        for issue in result.get('Vulnerabilities') or []:
            if issue.get('Severity') not in ('HIGH', 'CRITICAL'):
                continue
            row = {key: issue.get(key) for key in ('VulnerabilityID', 'PkgName', 'InstalledVersion', 'FixedVersion', 'Severity')}
            (fixed if issue.get('FixedVersion') else unfixed).append(row)
    return {'report': str(path), 'image_id': image, 'passed': not fixed,
            'fixable_high_critical': fixed, 'unfixed_high_critical': unfixed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports', nargs='+', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    results = [inspect(path) for path in args.reports]
    evidence = {'passed': all(row['passed'] for row in results), 'images': results}
    output = json.dumps(evidence, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output)
    else:
        print(output, end='')
    return 0 if evidence['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
