#!/usr/bin/env bash
# Render every layer to SVG, then to PNG through the Chrome for Testing already
# vendored for the UAT rounds. One source (the .py), two artefacts that cannot
# drift apart.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$(cd "$HERE/.." && pwd)"
CHROME="${CHROME:-$OUT/../../.uat-browser/chrome/mac_arm-152.0.7977.75/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing}"

cd "$HERE"
python3 render.py "$OUT"

for svg in "$OUT"/*.svg; do
  png="${svg%.svg}.png"
  dims="$(sed -n 's/.*<svg[^>]*width="\([0-9]*\)"[^>]*height="\([0-9]*\)".*/\1 \2/p;q' "$svg")"
  W="${dims%% *}"; H="${dims##* }"
  "$CHROME" --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=2 \
    --window-size="$W,$H" --screenshot="$png" "file://$svg" >/dev/null 2>&1
  printf '  %-34s %sx%s -> %s\n' "$(basename "$svg")" "$W" "$H" "$(basename "$png")"
done
