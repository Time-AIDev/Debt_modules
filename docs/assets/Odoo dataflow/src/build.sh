#!/usr/bin/env bash
# Render both sheets to SVG, then to PNG through the Chrome for Testing already
# vendored for the UAT rounds. One source (the .py), two artefacts that cannot
# drift apart. Same shape as docs/assets/HLD/src/build.sh, because it is the same job.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$(cd "$HERE/.." && pwd)"
# Glob the version rather than pin it: the UAT browser is refreshed from upstream
# and a pinned path turns a working toolchain into a broken one on the next bump.
if [ -z "${CHROME:-}" ]; then
  CHROME="$(ls -d "$OUT"/../../.uat-browser/chrome/*/chrome-mac-arm64/"Google Chrome for Testing.app"/Contents/MacOS/"Google Chrome for Testing" 2>/dev/null | tail -1)"
fi
[ -x "$CHROME" ] || { echo "no Chrome for Testing under .uat-browser; set CHROME=" >&2; exit 1; }

cd "$HERE"
python3 render.py "$OUT"

for svg in "$OUT"/*.svg; do
  png="${svg%.svg}.png"
  dims="$(sed -n 's/.*<svg[^>]*width="\([0-9]*\)"[^>]*height="\([0-9]*\)".*/\1 \2/p;q' "$svg")"
  W="${dims%% *}"; H="${dims##* }"
  "$CHROME" --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=2 \
    --window-size="$W,$H" --screenshot="$png" "file://$svg" >/dev/null 2>&1
  printf '  %-24s %sx%s -> %s\n' "$(basename "$svg")" "$W" "$H" "$(basename "$png")"
done
