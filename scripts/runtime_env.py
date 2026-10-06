#!/usr/bin/env python3
"""Render non-secret environment defaults from the application's release policy."""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.runtime_policy import environment_defaults


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--state", choices=("shared", "fixtures"), default="shared")
    parser.add_argument("--format", choices=("dotenv", "json", "gcloud"), default="dotenv")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    values = environment_defaults(args.environment, args.state)
    if args.format == "json": output = json.dumps(values, indent=2) + "\n"
    elif args.format == "gcloud": output = ",".join(k + "=" + v for k, v in values.items()) + "\n"
    else: output = "".join(k + "=" + v + "\n" for k, v in values.items())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as file: file.write(output)
        print("Wrote %d non-secret runtime settings" % len(values))
    else: print(output, end="")


if __name__ == "__main__": main()
