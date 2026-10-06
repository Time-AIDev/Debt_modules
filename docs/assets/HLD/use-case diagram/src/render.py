"""Render the use-case set. `python3 render.py <outdir>`

hld_lib is IMPORTED from the HLD set, never copied (the same rule the dataflow set
follows). The two sys.path lines are the whole of the coupling.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))

import d00_use_cases  # noqa: E402
import d01_register   # noqa: E402

SHEETS = [
    ("00-use-case-overview", d00_use_cases),
    ("01-use-case-register", d01_register),
]


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    for name, mod in SHEETS:
        path = os.path.join(out, name + ".svg")
        mod.build().save(path)
        print("  %s" % path)


if __name__ == "__main__":
    main()
