"""Render the Volt Debt GCP staging design set. `python3 render.py <outdir>`

The emitter is NOT copied: hld_lib.py is imported from docs/assets/HLD/src so the two
sets cannot drift into different house styles. One library, two sets.
"""
import sys, os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "HLD", "src")))

import d00_context, d01_topology, d02_data_path, d03_schema, d04_states, d05_delivery
import d06_onepage

SHEETS = [
    ("00-context", d00_context),
    ("01-topology", d01_topology),
    ("02-data-path", d02_data_path),
    ("03-schema", d03_schema),
    ("04-states-and-failure", d04_states),
    ("05-delivery-and-gaps", d05_delivery),
    ("06-one-page", d06_onepage),
]

def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    for name, mod in SHEETS:
        path = os.path.join(out, name + ".svg")
        mod.build().save(path)
        print("  %s" % path)

if __name__ == "__main__":
    main()
