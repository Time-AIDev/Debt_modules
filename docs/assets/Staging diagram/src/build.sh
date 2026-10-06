#!/usr/bin/env bash
# Render every sheet to SVG, then to PNG through the Chrome for Testing already
# vendored for the UAT rounds. One source (the .py), two artefacts that cannot drift.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$(cd "$HERE/.." && pwd)"
# Whichever Chrome for Testing version the UAT rounds last installed — a pinned version
# folder broke this the first time .uat-browser was upgraded.
if [ -z "${CHROME:-}" ]; then
  CHROME="$(ls -d "$OUT"/../../.uat-browser/chrome/mac_arm-*/chrome-mac-arm64/"Google Chrome for Testing.app"/Contents/MacOS/"Google Chrome for Testing" 2>/dev/null | tail -1)"
fi
[ -x "$CHROME" ] || { echo "No Chrome for Testing found; set CHROME=/path/to/chrome" >&2; exit 1; }

cd "$HERE"
python3 render.py "$OUT"

for svg in "$OUT"/*.svg; do
  png="${svg%.svg}.png"
  dims="$(sed -n 's/.*<svg[^>]*width="\([0-9]*\)"[^>]*height="\([0-9]*\)".*/\1 \2/p;q' "$svg")"
  W="${dims%% *}"; H="${dims##* }"
  "$CHROME" --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=2 \
    --window-size="$W,$H" --screenshot="$png" "file://${svg// /%20}" >/dev/null 2>&1
  printf '  %-30s %sx%s -> %s\n' "$(basename "$svg")" "$W" "$H" "$(basename "$png")"
done
