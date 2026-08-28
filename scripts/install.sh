#!/usr/bin/env bash
# install.sh — deploy dist/busdriver/ to the Move.
# Usage: scripts/install.sh              (WiFi, move.local)
#        MOVE_HOST=172.16.254.1 scripts/install.sh   (USB tether)
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
MODULE_ID=busdriver
HOST="${MOVE_HOST:-move.local}"
DEST="/data/UserData/schwung/modules/audio_fx/${MODULE_ID}"

[ -d "$HERE/dist/${MODULE_ID}" ] || { echo "run scripts/build.sh first" >&2; exit 1; }

echo "==> installing to ableton@${HOST}:${DEST}"
ssh "ableton@${HOST}" "mkdir -p '${DEST}'"
# temp-name + mv to dodge ETXTBSY if the .so is currently loaded
scp "$HERE/dist/${MODULE_ID}/${MODULE_ID}.so" "ableton@${HOST}:${DEST}/.${MODULE_ID}.so.new"
ssh "ableton@${HOST}" "mv -f '${DEST}/.${MODULE_ID}.so.new' '${DEST}/${MODULE_ID}.so'"
for f in module.json help.json canvas.js; do
    [ -f "$HERE/dist/${MODULE_ID}/$f" ] && scp "$HERE/dist/${MODULE_ID}/$f" "ableton@${HOST}:${DEST}/"
done
ssh "ableton@${HOST}" "chmod -R a+rw '${DEST}'"

# Factory Module Presets → /data/UserData/schwung/presets/busdriver/
if [ -d "$HERE/src/presets/${MODULE_ID}" ]; then
    PDEST="/data/UserData/schwung/presets/${MODULE_ID}"
    echo "==> installing factory presets to ${PDEST}"
    ssh "ableton@${HOST}" "mkdir -p '${PDEST}'"
    scp "$HERE/src/presets/${MODULE_ID}/"*.json "ableton@${HOST}:${PDEST}/"
    ssh "ableton@${HOST}" "chmod -R a+rw '${PDEST}'"
fi
echo "==> installed. Swap the FX out/in (or restart) to reload a live .so."
