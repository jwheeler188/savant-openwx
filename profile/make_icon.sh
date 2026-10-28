#!/bin/bash
# Builds blueprint-import/openwx_weatherbridge.icns (Blueprint's component icon) from icon.svg. macOS only:
# Quick Look renders the SVG, sips scales it, iconutil packs the .icns.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
qlmanage -t -s 1024 -o "$TMP" "$HERE/icon.svg" >/dev/null 2>&1
PNG="$TMP/icon.svg.png"
[ -f "$PNG" ] || { echo "Quick Look could not render icon.svg" >&2; exit 1; }
SET="$TMP/openwx_weatherbridge.iconset"; mkdir "$SET"
for s in 16 32 128 256 512; do
  sips -z $s $s "$PNG" --out "$SET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) "$PNG" --out "$SET/icon_${s}x${s}@2x.png" >/dev/null
done
mkdir -p "$HERE/blueprint-import"
iconutil -c icns "$SET" -o "$HERE/blueprint-import/openwx_weatherbridge.icns"
echo "wrote blueprint-import/openwx_weatherbridge.icns"
