"""Render the dataflow set. `python3 render.py <outdir>`

hld_lib is IMPORTED from the HLD set, never copied: one drawing library, so a
change to a tone or an arrow head shows up on every sheet the project has rather
than on half of them. The two sys.path lines are the whole of the coupling.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))

import d00_level0   # noqa: E402
import d01_intake   # noqa: E402
import d02_work     # noqa: E402
import d03_outputs  # noqa: E402
import d04_money    # noqa: E402

SHEETS = [
    ("00-level-0-context", d00_level0),
    ("01-level-1-intake-and-book", d01_intake),
    ("02-level-1-collections", d02_work),
    ("03-level-1-books-outputs-and-audit", d03_outputs),
    ("04-money-engine-detail", d04_money),
]


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    for name, mod in SHEETS:
        path = os.path.join(out, name + ".svg")
        mod.build().save(path)
        print("  %s" % path)


if __name__ == "__main__":
    main()
