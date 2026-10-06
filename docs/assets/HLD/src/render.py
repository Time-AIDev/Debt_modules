"""Render the Volt Debt HLD set. `python3 render.py <outdir>`"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import d00_context, d01_client, d02_api, d03_domain, d04_data, d05_deploy

SHEETS = [
    ("00-context", d00_context),
    ("01-client-layer", d01_client),
    ("02-api-layer", d02_api),
    ("03-domain-layer", d03_domain),
    ("04-data-and-state", d04_data),
    ("05-runtime-and-deployment", d05_deploy),
]

def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    for name, mod in SHEETS:
        path = os.path.join(out, name + ".svg")
        mod.build().save(path)
        print("  %s" % path)

if __name__ == "__main__":
    main()
