#!/usr/bin/env bash
# Flash one MaUWB_DW3000 board.
#
#   ./flash.sh                          # selftest.ino, auto-detect the port
#   ./flash.sh /dev/cu.usbserial-0001   # selftest.ino on that port
#   ./flash.sh bridge                   # bridge.ino, for ranging.py (phase B)
#   ./flash.sh bridge /dev/cu.usbserial-0001
#
# The FQBN is pinned here on purpose. Ten boards, one command, zero chance the
# settings drift between board 1 and board 10 -- PSRAM=enabled in particular is
# the one everybody forgets in the GUI, and forgetting it makes ten good boards
# report a PSRAM failure.
set -euo pipefail

FQBN="esp32:esp32:esp32:PSRAM=enabled"
HERE="$(cd "$(dirname "$0")" && pwd)"

NAME=selftest
case "${1:-}" in
  selftest|bridge) NAME="$1"; shift ;;
esac
SKETCH="$HERE/$NAME"

PORT="${1:-}"
if [ -z "$PORT" ]; then
  CAND=$(ls /dev/cu.usbserial* /dev/cu.usbmodem* /dev/cu.wchusbserial* \
            /dev/cu.SLAB_USBtoUART* 2>/dev/null || true)
  N=$(printf '%s\n' "$CAND" | grep -c . || true)
  if [ "$N" -eq 1 ]; then
    PORT="$CAND"
  elif [ "$N" -eq 0 ]; then
    echo "No USB serial port found."
    echo "  - is the board plugged in with a DATA cable, not a charge-only one?"
    echo "  - ls /dev/cu.*   to see everything"
    exit 1
  else
    echo "More than one candidate; pass the port explicitly:"
    printf '  %s\n' $CAND
    exit 1
  fi
fi

echo "sketch  $NAME"
echo "port    $PORT"
echo "fqbn    $FQBN"
echo

arduino-cli compile --fqbn "$FQBN" "$SKETCH"
echo
arduino-cli upload -p "$PORT" --fqbn "$FQBN" "$SKETCH"

# Quoted, because this folder's path has a space in it and an unquoted copy
# of the command splits there.
echo
echo "Flashed $NAME. Now:"
if [ "$NAME" = bridge ]; then
  echo "  python3 \"$HERE/ranging.py\" anchor --id <REF-ID>     # reference board, once"
  echo "  python3 \"$HERE/ranging.py\" tag --id <BOARD-ID> --ref <REF-ID> --distance <metres>"
else
  echo "  python3 \"$HERE/selftest.py\" --id <BOARD-ID> --tester <INITIALS>"
fi
