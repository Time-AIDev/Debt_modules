"""Render the Volt Debt staging-stack set. `python3 render.py <outdir>`

The emitter is NOT copied: hld_lib.py is imported from docs/assets/HLD/src, as the GCP
design set does, so all three diagram sets share one house style.
"""
import sys, os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "HLD", "src")))

import s00_path, s01_free_uat, s02_gcp

SHEETS = [
    ("00-the-path", s00_path),
    ("01-free-uat-stack", s01_free_uat),
    ("02-gcp-staging-stack", s02_gcp),
]


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    for name, mod in SHEETS:
        path = os.path.join(out, name + ".svg")
        mod.build().save(path)
        print("  %s" % path)


if __name__ == "__main__":
    main()
