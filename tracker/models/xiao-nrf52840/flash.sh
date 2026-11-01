#!/usr/bin/env bash
# Flash the function self-test onto one Seeed XIAO nRF52840.
#
#   ./flash.sh                          # auto-detect the port
#   ./flash.sh /dev/cu.usbmodem101      # that port
#   FQBN=Seeeduino:nrf52:xiaonRF52840Sense ./flash.sh   # a Sense board
#
# Board package: "Seeed nRF52 Boards" (not the mbed one), which carries the
# Bluefruit BLE library the self-test uses. Once per Mac:
#   arduino-cli core install Seeeduino:nrf52 \
#     --additional-urls https://files.seeedstudio.com/arduino/package_seeeduino_boards_index.json
#
# The FQBN is pinned so every XIAO is built the same way.
set -euo pipefail

FQBN="${FQBN:-Seeeduino:nrf52:xiaonRF52840}"
HERE="$(cd "$(dirname "$0")" && pwd)"

# The Seeed package hands the sketch folder to the compiler unquoted
# (-I{build.source.path} in its platform.txt), so a path with a space in it,
# like "eece job", breaks the build. Build from a copy in a temp folder.
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp -R "$HERE/selftest" "$WORK/selftest"
SKETCH="$WORK/selftest"

PORT="${1:-}"
if [ -z "$PORT" ]; then
  CAND=$(ls /dev/cu.usbmodem* 2>/dev/null || true)
  N=$(printf '%s\n' "$CAND" | grep -c . || true)
  if [ "$N" -eq 1 ]; then
    PORT="$CAND"
  elif [ "$N" -eq 0 ]; then
    echo "No XIAO port found."
    echo "  - is it plugged in with a DATA cable, not a charge-only one?"
    echo "  - is the bench supply off its 5V pin? Never have both."
    echo "  - ls /dev/cu.*   to see everything"
    exit 1
  else
    echo "More than one candidate; pass the port explicitly:"
    printf '  %s\n' $CAND
    exit 1
  fi
fi

echo "sketch  selftest"
echo "port    $PORT"
echo "fqbn    $FQBN"
echo

arduino-cli compile --fqbn "$FQBN" "$SKETCH"
echo
arduino-cli upload -p "$PORT" --fqbn "$FQBN" "$SKETCH"

# Quoted, because this folder's path has a space in it.
echo
echo "Flashed selftest. Wait about 6 s for its BLE scan, then:"
echo "  python3 \"$HERE/selftest.py\" --id <XIAO-ID> --tester <INITIALS>"
