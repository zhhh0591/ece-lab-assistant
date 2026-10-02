#!/usr/bin/env python3
"""
Phase B for MaUWB_DW3000 boards: UWB ranging against a reference board.

    python3 ranging.py --list
    python3 ranging.py anchor --id ECE-0101                          # once
    python3 ranging.py tag --id ECE-0102 --ref ECE-0101 --distance 2.00

Both boards run bridge/bridge.ino (./flash.sh bridge). The ESP32 is only a
wire; this script talks straight to the STM32 that does the UWB work, using
the commands in Makerfabs' "UWB AT Module AT Command Manual" v1.1.2.

  anchor   makes the reference board anchor A0 and saves that in the module,
           so it keeps the role on any USB charger, away from the Mac.
  tag      makes the board under test tag T0, collects its distance reports,
           judges them, and records the run.

What it decides -- deliberately only one thing:
  PASS  the board ranges: at least MIN_READINGS distances to the reference
        anchor arrived in the window.
  FAIL  it does not.

What it does NOT decide is whether the distance is "right". These boards read
long until they are calibrated -- an independent review of this exact board
measured offsets of 50-61 cm -- and the offset belongs to the pair, not to one
board. So the offset is recorded and set beside the rest of the batch. Turning
it into a pass/fail limit would mean inventing a tolerance nobody measured.

Every run goes to ../../ranging.jsonl with all its raw readings (phase C fits
the calibration from those). A FAIL also goes into ../../boards.csv.
"""

import argparse
import json
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import serial

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from log import read_rows, write_rows          # noqa: E402
from selftest import pick_port                 # noqa: E402

HERE = Path(__file__).resolve().parent
TRACKER = HERE.parents[1]
RANGING = TRACKER / "ranging.jsonl"
RESULTS = TRACKER / "results.jsonl"

BAUD = 115200

# The network. Anchor and tag get the same values; the module needs that.
ANCHOR_ID = 0           # the reference board is anchor A0
TAG_ID = 0              # the board under test is tag T0 -- so power only these two
RATE = 0                # 0 = 850 kbps: slower, but more robust than 1 = 6.8 Mbps
FILTER = 1              # the module's own range filter, on as Makerfabs advises
TAGS, SLOT_MS = 10, 15  # 10 tag slots x 15 ms = one report every 150 ms (~6.7/s)

SECONDS = 15            # how long to collect
WARMUP_S = 2            # skipped after the restart, while the tag finds the anchor
MIN_READINGS = 10       # fewer than this and there is nothing to take a median of

OWN = "UWB ranging:"    # the known_issues entries this script writes, and owns


# ==========================================================================
# PARSING. Pure: one line of text in, numbers out.
# ==========================================================================

FIELD = re.compile(r"(\w+):(\([^)]*\)|[^,]+)")


def parse_range(line):
    """One distance report -> {anchor id: distance in cm}, valid slots only.

    v1.1.6 firmware (manual v1.1.2):
      AT+RANGE=tid:0,mask:01,seq:205,range:(90,0,0,0,0,0,0,0),ancid:(0,-1,-1,-1,-1,-1,-1,-1)
    older firmware (Makerfabs' get_range.ino):
      AT+RANGE=tid:1,mask:04,seq:63,range:(0,0,30,0,0,0,0,0),rssi:(0.00,0.00,-77.93,...)

    Older firmware: slot i is anchor i. Newer firmware may pick any 8 anchors,
    so slot i belongs to ancid[i]. mask (hex) says which slots hold a real
    distance this time. We do not know which firmware each board shipped with,
    so this reads both.
    """
    if not line.startswith("AT+RANGE="):
        return None
    f = dict(FIELD.findall(line[len("AT+RANGE="):]))
    try:
        mask = int(f["mask"], 16)
        cm = [int(x) for x in f["range"].strip("()").split(",")]
        ids = ([int(x) for x in f["ancid"].strip("()").split(",")]
               if "ancid" in f else list(range(len(cm))))
    except (KeyError, ValueError):
        return None
    return {ids[i]: cm[i] for i in range(min(len(cm), len(ids)))
            if mask >> i & 1 and cm[i] > 0 and ids[i] >= 0}


# ==========================================================================
# RULES. Pure: readings in, (verdict, why, numbers) out. Same split as
# selftest.py -- where the numbers come from is somebody else's problem.
# ==========================================================================

def judge(readings, reports, actual_m, seconds):
    n = len(readings)
    if n < MIN_READINGS:
        if reports == 0:
            why = ("no distance reports at all -- most often the reference anchor "
                   "is off or too far away. Check it and re-run before believing this")
        else:
            why = (f"{reports} reports, but only {n} with a distance to anchor "
                   f"A{ANCHOR_ID} (need {MIN_READINGS})")
        return "FAIL", why, {}

    med = statistics.median(readings) / 100
    nums = {
        "readings": n,
        "expected": round(seconds * 1000 / (TAGS * SLOT_MS)),
        "median_m": round(med, 3),
        "min_m": min(readings) / 100,
        "max_m": max(readings) / 100,
        "stdev_m": round(statistics.pstdev(readings) / 100, 3),
        "offset_m": round(med - actual_m, 3),
    }
    return "PASS", f"ranges: median {med:.2f} m at {actual_m:.2f} m", nums


# ==========================================================================
# THE BOARD. Everything that touches the serial port.
# ==========================================================================

class Board:
    """One board on one USB port, running bridge.ino."""

    def __init__(self, port):
        try:
            self.ser = serial.Serial(port, BAUD, timeout=0.2)
        except serial.SerialException as e:
            sys.exit(f"\n  cannot open {port}: {e}")
        self.heard = []                  # replies that were not the one we wanted

    def readline(self):
        raw = self.ser.readline()        # waits at most `timeout`
        return raw.decode("utf-8", "replace").strip() if raw else None

    def send(self, line):
        self.ser.write((line + "\r\n").encode())

    def ask(self, cmd, expect="OK", seconds=2.0):
        """Send one AT command; return the first reply that starts with
        `expect`, or None. Distance reports keep arriving in between -- skip
        them, they are not the answer."""
        self.ser.reset_input_buffer()
        self.send(cmd)
        self.heard = []
        end = time.time() + seconds
        while time.time() < end:
            ln = self.readline()
            if not ln or ln.startswith("AT+RANGE"):
                continue
            if ln.startswith(expect):
                return ln
            self.heard.append(ln)
        return None

    def hello(self):
        """-> the MAC the board reports. This is what proves which board is
        on the port: ten identical boards and no labels yet."""
        # Reset the ESP32 over DTR/RTS, as selftest.py does, so the boot banner
        # comes out. Not every adapter can; asking BRIDGE? works either way.
        try:
            self.ser.setDTR(False)
            self.ser.setRTS(True)
            time.sleep(0.15)
            self.ser.reset_input_buffer()
            self.ser.setRTS(False)
        except (serial.SerialException, OSError):
            pass
        t0, asked = time.time(), 0
        while time.time() - t0 < 8:
            if asked < 3 and time.time() - t0 > 2 * (asked + 1):
                self.send("BRIDGE?")
                asked += 1
            ln = self.readline()
            if not ln:
                continue
            if ln.startswith("BRIDGE "):
                m = re.search(r"mac=([0-9A-F:]{17})", ln)
                return m.group(1) if m else ""
            if "SELFTEST" in ln:
                sys.exit("\n  This board is running the self-test firmware, not the bridge.\n"
                         "  Flash it first:  ./flash.sh bridge")
        sys.exit("\n  No answer from the bridge. Is bridge.ino flashed (the screen says\n"
                 "  UWB BRIDGE)? Is this the right port (ranging.py --list)?")

    def refused(self, cmd):
        heard = " | ".join(self.heard[-3:]) or "nothing"
        sys.exit(f"\n  {cmd}: no OK from the module (heard: {heard})")

    def configure(self, role):
        """Makerfabs' sequence: test, wipe, set, save, restart. Then read the
        settings back -- an OK only means "received", not "done"."""
        anchor = role == "anchor"
        cfg = f"{ANCHOR_ID if anchor else TAG_ID},{1 if anchor else 0},{RATE},{FILTER}"

        if not self.ask("AT?"):
            sys.exit("\n  The STM32 does not answer AT? through the bridge, so the UWB\n"
                     "  half of this board is not talking. Did it pass the self-test?")
        version = (self.ask("AT+GETVER?", "AT+GETVER=") or "=unknown").split("=", 1)[1]

        # Firmware before v1.1.1 takes AT+SETCAP=<tags>,<slot>; later firmware
        # added a third field (extended packets). Rather than guess the version,
        # ask how many fields this board reports and answer in the same shape.
        cap = self.ask("AT+GETCAP?", "AT+GETCAP=") or ""
        setcap = [f"AT+SETCAP={TAGS},{SLOT_MS},0", f"AT+SETCAP={TAGS},{SLOT_MS}"]
        if cap.count(",") == 1:
            setcap.reverse()

        if not self.ask("AT+RESTORE", "OK", 5):
            self.refused("AT+RESTORE")
        time.sleep(1)                    # Makerfabs' own code waits after this one
        if not self.ask(f"AT+SETCFG={cfg}"):
            self.refused(f"AT+SETCFG={cfg}")
        if not any(self.ask(c) for c in setcap):
            self.refused(setcap[0])
        for cmd in ("AT+SETRPT=1", "AT+SAVE", "AT+RESTART"):
            if not self.ask(cmd):
                self.refused(cmd)

        time.sleep(2)                    # the module restarting
        got = self.ask("AT+GETCFG?", "AT+GETCFG=", 4)
        if not got or got.split("=", 1)[1] != cfg:
            sys.exit(f"\n  Settings did not stick: wrote {cfg}, module reports "
                     f"{got or 'nothing'}")
        got = self.ask("AT+GETCAP?", "AT+GETCAP=", 2) or ""
        if not got.startswith(f"AT+GETCAP={TAGS},{SLOT_MS}"):
            sys.exit(f"\n  Capacity did not stick: module reports {got or 'nothing'}")
        return version, cfg

    def collect(self, seconds):
        """Distance reports for `seconds` -> (readings in cm, reports seen)."""
        end = time.time() + WARMUP_S
        while time.time() < end:
            self.readline()
        readings, reports = [], 0
        end = time.time() + seconds
        while time.time() < end:
            ln = self.readline()
            if not ln or not ln.startswith("AT+RANGE="):
                continue
            reports += 1
            d = parse_range(ln)
            if d and ANCHOR_ID in d:
                readings.append(d[ANCHOR_ID])
                print(f"\r    {len(readings):>3} readings   last {d[ANCHOR_ID] / 100:.2f} m ",
                      end="", flush=True)
        print()
        return readings, reports


# ==========================================================================
# RECORDS
# ==========================================================================

def load_jsonl(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def find_board(rows, board_id):
    for r in rows:
        if r["id"] == board_id:
            return r
    sys.exit(f"\n  {board_id} is not in boards.csv. Phase B is for boards that passed\n"
             f"  the self-test -- run  selftest.py --id {board_id}  first.")


def check_identity(row, mac):
    want = re.search(r"MAC ([0-9A-F:]{17})", row["notes"])
    if not want:
        sys.exit(f"\n  boards.csv has no MAC for {row['id']}, so nothing proves which\n"
                 f"  board this is. Run  selftest.py --id {row['id']}  first.")
    if mac != want.group(1):
        sys.exit(f"\n  Wrong board? {row['id']} is recorded as MAC {want.group(1)},\n"
                 f"  but the board on this port reports {mac}.")


def latest_selftest(board_id):
    runs = [r for r in load_jsonl(RESULTS) if r.get("id") == board_id]
    return runs[-1].get("verdict") if runs else None


def batch_offsets(ref, board_id):
    """Latest offset of every other board ranged against `ref`, if it passed."""
    latest = {}
    for r in load_jsonl(RANGING):
        if r.get("ref") == ref and r.get("id") != board_id:
            latest[r["id"]] = r          # the file is in time order; last wins
    return [r["offset_m"] for r in latest.values() if r.get("verdict") == "PASS"]


def update_board(rows, row, verdict, why, ref, actual_m, nums, tester):
    """Add or clear this script's own entry. Never touch the self-test's."""
    issues = [s for s in row["known_issues"].split("; ")
              if s and not s.startswith(OWN)]
    notes = [s for s in row["notes"].split("; ") if s and not s.startswith("UWB")]
    if verdict == "FAIL":
        issues.append(f"{OWN} {why}")
        row["status"] = "FAIL"
    else:
        notes.append(f"UWB vs {ref} @{actual_m:.2f}m read {nums['median_m']:.2f}m")
        # ranging was the only thing holding it back -> back to PASS
        if not issues and latest_selftest(row["id"]) == "PASS":
            row["status"] = "PASS"
    row["known_issues"] = "; ".join(issues)
    row["notes"] = "; ".join(notes)
    row["last_tested"] = datetime.now().date().isoformat()
    row["tested_by"] = tester or row["tested_by"]
    write_rows(rows)


# ==========================================================================

def run_anchor(a):
    row = find_board(read_rows(), a.id)
    port = pick_port(a.port)
    print(f"\n  {a.id} on {port}")
    board = Board(port)
    mac = board.hello()
    check_identity(row, mac)
    print(f"  bridge   MAC {mac}  (matches boards.csv)")
    version, _ = board.configure("anchor")
    print(f"  module   {version}")
    print(f"  set      anchor A{ANCHOR_ID}, 850 kbps, filter on, "
          f"{TAGS} x {SLOT_MS} ms -- saved and read back")
    print(f"""
  {a.id} is now the reference anchor. The role is saved in the module, so
  it can run from any USB charger or power bank, away from the Mac.

  Put it at one fixed spot for the whole batch: on something non-metal, at
  the same height as the boards you test, at least 1 m from walls and metal.
""")


def run_tag(a):
    if a.ref == a.id:
        sys.exit("\n  A board cannot range against itself -- --ref is the anchor board.")
    rows = read_rows()
    row = find_board(rows, a.id)
    find_board(rows, a.ref)
    port = pick_port(a.port)
    print(f"\n  {a.id} on {port}")
    board = Board(port)
    mac = board.hello()
    check_identity(row, mac)
    print(f"  bridge   MAC {mac}  (matches boards.csv)")
    if row["status"] == "FAIL" and not row["known_issues"].startswith(OWN):
        print(f"  note     {a.id} failed the self-test ({row['known_issues']}).\n"
              f"           Ranging it anyway; a PASS here will not clear that.")
    version, _ = board.configure("tag")
    print(f"  module   {version}")
    print(f"  set      tag T{TAG_ID} -- saved and read back")

    print(f"\n  Reference {a.ref} as A{ANCHOR_ID}, {a.distance:.2f} m away. "
          f"Collecting for {a.seconds:.0f} s...")
    readings, reports = board.collect(a.seconds)
    verdict, why, nums = judge(readings, reports, a.distance, a.seconds)
    others = batch_offsets(a.ref, a.id)

    print("\n" + "=" * 66)
    if verdict == "FAIL":
        print(f"  {a.id}: FAIL  (UWB ranging)\n    {why}")
    else:
        print(f"  {a.id}: PASS  -- it ranges")
        print(f"    readings   {nums['readings']} of ~{nums['expected']} expected")
        print(f"    distance   median {nums['median_m']:.2f} m  (min {nums['min_m']:.2f}, "
              f"max {nums['max_m']:.2f}, stdev {nums['stdev_m']:.2f})")
        print(f"    offset     {nums['offset_m']:+.2f} m against the tape measure")
        if others:
            print(f"    batch      other boards vs {a.ref}: {min(others):+.2f} to "
                  f"{max(others):+.2f} m ({len(others)} board{'s' * (len(others) > 1)})")
        print("  The offset is a calibration number (phase C), not a fault.")
    print("=" * 66 + "\n")

    with RANGING.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "id": a.id, "mac": mac, "ref": a.ref,
            "anchor": ANCHOR_ID, "tag": TAG_ID,
            "actual_m": a.distance, "seconds": a.seconds,
            "firmware": version, "tester": a.tester,
            "verdict": verdict, "why": why, **nums,
            "reports": reports, "readings_cm": readings,
        }, ensure_ascii=False) + "\n")
    update_board(rows, row, verdict, why, a.ref, a.distance, nums, a.tester)
    print(f"  wrote {TRACKER.name}/ranging.jsonl and {TRACKER.name}/boards.csv\n")


def main():
    ap = argparse.ArgumentParser(description="Phase B: UWB ranging against a reference board")
    ap.add_argument("--list", action="store_true", help="show the serial ports")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("anchor", help="make the reference board anchor A0 (once)")
    p.add_argument("--id", required=True)
    p.add_argument("--port")

    p = sub.add_parser("tag", help="range a board against the reference")
    p.add_argument("--id", required=True)
    p.add_argument("--ref", required=True, help="the board set up with 'anchor'")
    p.add_argument("--distance", type=float, required=True,
                   help="tape-measured, antenna to antenna, in metres")
    p.add_argument("--seconds", type=float, default=SECONDS)
    p.add_argument("--tester", default="")
    p.add_argument("--port")
    a = ap.parse_args()

    if a.list:
        import serial.tools.list_ports
        for p in serial.tools.list_ports.comports():
            print(f"  {p.device:<28} {p.description}")
    elif a.cmd == "anchor":
        run_anchor(a)
    elif a.cmd == "tag":
        run_tag(a)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
