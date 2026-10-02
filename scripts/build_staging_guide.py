#!/usr/bin/env python3
"""Build the UAT guidebook page that gets deployed — passwords injected, never committed.

The repo's rule is that a password never enters git (see `.gitignore`'s
`docs/guides/*with-passwords*` and the vault note itself). The tester page needs the
passwords on it, so the tracked file is a template with `{{ROLE_PW}}` slots and this
script fills them from the vault note at build time, writing to `build/staging-guide/`
(gitignored). Netlify is deployed from there:

    python scripts/build_staging_guide.py
    netlify deploy --dir build/staging-guide --prod --site volt-debt-uat-guide

The vault path can be pointed elsewhere with STAGING_ACCOUNTS_NOTE. The script prints
role names and password LENGTHS only — never a password — so a CI log or a terminal
scrollback stays safe.
"""
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "docs" / "staging-guide" / "index.template.html"
NETLIFY_TOML = ROOT / "docs" / "staging-guide" / "netlify.toml"
OUT_DIR = ROOT / "build" / "staging-guide"
DEFAULT_NOTE = Path.home() / "Documents" / "Obsidian Vault" / "Debt modules (self build)" / "staging" / "01 - Tester accounts และรหัสผ่าน.md"

# | `officer` | OFFICER | `password` | ...
ROW = re.compile(r"^\|\s*`(?P<user>[a-z]+)`\s*\|\s*(?P<role>[A-Z]+)\s*\|\s*`(?P<pw>[^`]+)`\s*\|", re.M)


def passwords_from_note(path):
    """{ROLE: password} from the vault note's account table."""
    if not path.is_file():
        raise SystemExit("the accounts note is missing: %s\n"
                         "point STAGING_ACCOUNTS_NOTE at it, or write it first" % path)
    rows = ROW.findall(path.read_text(encoding="utf-8"))
    found = {role: pw for _user, role, pw in rows}
    missing = [role for role in ("OFFICER", "SUPERVISOR", "MANAGER", "OWNER") if role not in found]
    if missing:
        raise SystemExit("the note has no password row for: %s\n"
                         "(expected lines like | `officer` | OFFICER | `…` |)" % ", ".join(missing))
    return found


def main():
    note = Path(os.environ.get("STAGING_ACCOUNTS_NOTE", str(DEFAULT_NOTE)))
    passwords = passwords_from_note(note)
    html = TEMPLATE.read_text(encoding="utf-8")

    for role, password in passwords.items():
        html = html.replace("{{%s_PW}}" % role, password)

    leftover = sorted(set(re.findall(r"\{\{[A-Z_]+_PW\}\}", html)))
    if leftover:
        raise SystemExit("unfilled slots remain: %s" % ", ".join(leftover))
    if any(pw in TEMPLATE.read_text(encoding="utf-8") for pw in passwords.values()):
        raise SystemExit("REFUSING: a password is already present in the tracked template")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "index.html").write_text(html, encoding="utf-8")
    shutil.copyfile(NETLIFY_TOML, OUT_DIR / "netlify.toml")
    headers = NETLIFY_TOML.with_name("_headers")
    if headers.is_file():
        shutil.copyfile(headers, OUT_DIR / "_headers")

    print("built %s" % (OUT_DIR / "index.html").relative_to(ROOT))
    print("passwords injected from %s" % note.name)
    for role in ("OFFICER", "SUPERVISOR", "MANAGER", "OWNER"):
        print("  %-11s length %d" % (role, len(passwords[role])))
    print("\nDeploy with:\n  netlify deploy --dir build/staging-guide --prod --site volt-debt-uat-guide")
    return 0


if __name__ == "__main__":
    sys.exit(main())
