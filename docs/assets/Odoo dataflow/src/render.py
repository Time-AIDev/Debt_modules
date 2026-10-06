"""Render the Odoo dataflow set. `python3 render.py <outdir>`

hld_lib is IMPORTED from the HLD set, never copied: one drawing library, so a
change to a tone or an arrow head shows up on every sheet the project has rather
than on half of them. The sys.path line is the whole of the coupling.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "HLD", "src"))

import d00_dataflow  # noqa: E402
import d01_rules     # noqa: E402

SHEETS = [
    ("00-dataflow", d00_dataflow),
    ("01-rules", d01_rules),
]


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    for name, mod in SHEETS:
        path = os.path.join(out, name + ".svg")
        mod.build().save(path)
        print("  %s" % path)


if __name__ == "__main__":
    main()
