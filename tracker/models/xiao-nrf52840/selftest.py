#!/usr/bin/env python3
"""
Function self-test for a Seeed XIAO nRF52840: step 8 of the Test Procedure.

    python3 selftest.py --list
    python3 selftest.py --id XIAO1 --tester HZ
    python3 selftest.py --id XIAO1 --report saved.txt --led y   # grade a saved report

Flash selftest/selftest.ino once first (./flash.sh). Then plug the XIAO into
the Mac with a data cable, run this, and watch the LED when it says so. The
bench supply must NOT be on the XIAO's 5V pin while it is on the Mac.

What each check proves
  CHIP   the right chip, running our code         nRF52840 factory registers
  ADDR   this board's unique id                   not judged; tells XIAO1 from XIAO2
  VBUS   the chip sees 5 V from USB               POWER.USBREGSTATUS
  VDD    the 3.3 V regulator, measured on-chip    3.3 V +/- 5 %
  HFCLK  the 32 MHz crystal runs                  CLOCK.HFCLKSTAT
  LFCLK  the 32.768 kHz clock runs                crystal or internal RC
  BLE    radio and antenna hear advertisers       any BLE device in 5 s
  LED    red, green and blue all light            a person watches

Electrical checks (short, current, rail voltages with a meter) are steps 1 to
7, done by hand. This one fills column S, "8 Function", of the sheet.
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRACKER = HERE.parents[1]
RESULTS = TRACKER / "results.jsonl"
MODEL = "Seeed XIAO nRF52840"

BAUD = 115200
READ_TIMEOUT_S = 30
V33_NOM, V33_TOL_FRAC = 3.3, 0.05

KV = re.compile(r"^([A-Z0-9]+)\s+(.*)$")
FIELD = re.compile(r"(\w+)=(\"[^\"]*\"|\S+)")


# ==========================================================================
# RULES. Parsed report in, (ok, why) out. Same split as the MaUWB self-test.
# ==========================================================================

def check_chip(f):
    part = f.get("part", "").lower()
    if part != "52840":
        return False, f"part {part or '?'}: not an nRF52840"
    return True, (f"nRF52840 variant {f.get('variant')}, "
                  f"{f.get('flash_kb')} KB flash, {f.get('ram_kb')} KB RAM")


def check_addr(f):
    i = f.get("id", "")
    return (True, i) if i else (None, "no id reported")


def check_vbus(f):
    if f.get("detect") != "1":
        return False, "chip does not see 5 V on VBUS: cable, USB-C contacts or VBUS trace"
    return True, "5 V present on VBUS"


def check_vdd(f):
    try:
        v = float(f.get("v", ""))
    except ValueError:
        return False, "no reading"
    tol = V33_NOM * V33_TOL_FRAC
    lo, hi = round(V33_NOM - tol, 3), round(V33_NOM + tol, 3)
    if lo <= v <= hi:
        return True, f"{v:.2f} V on-chip (want {lo:g} to {hi:g})"
    return False, f"{v:.2f} V is outside {lo:g} to {hi:g}: 3.3 V regulator suspect"


def check_hfclk(f):
    if f.get("running") != "1":
        return False, "32 MHz clock not running"
    if f.get("src") != "xtal":
        return False, "running from the internal RC: 32 MHz crystal did not start"
    return True, "32 MHz crystal running"


def check_lfclk(f):
    if f.get("running") != "1":
        return False, "32.768 kHz clock not running"
    if f.get("src") != "xtal":
        return True, f"running from {f.get('src')} (the board package chose it; crystal not exercised)"
    return True, "32.768 kHz crystal running"


def check_ble(f):
    n, dev = int(f.get("reports", 0)), int(f.get("devices", 0))
    if n == 0:
        return False, ("heard no BLE advertisers in 5 s. Put a phone with Bluetooth on "
                       "next to it and retest before blaming the radio")
    return True, f"{dev} devices, {n} adverts, best {f.get('best_rssi')} dBm"


def check_led(saw):
    if saw is None:
        return None, "not asked"
    return (True, "red, green and blue all lit") if saw else (False, "a colour did not light")


CHECKS = [
    ("CHIP",  "chip",               check_chip,  True),
    ("ADDR",  "board id",           check_addr,  False),
    ("VBUS",  "USB 5 V seen",       check_vbus,  True),
    ("VDD",   "3.3 V rail",         check_vdd,   True),
    ("HFCLK", "32 MHz crystal",     check_hfclk, True),
    ("LFCLK", "32.768 kHz clock",   check_lfclk, True),
    ("BLE",   "BLE radio",          check_ble,   True),
]


# ==========================================================================

def parse(lines):
    out = {}
    for ln in lines:
        m = KV.match(ln.strip())
        if not m:
            continue
        key, rest = m.group(1), m.group(2)
        out[key] = {k: v.strip('"') for k, v in FIELD.findall(rest)}
        out[key]["_raw"] = rest
    return out


def between_markers(lines):
    """Lines strictly between SELFTEST-BEGIN and SELFTEST-END, or None."""
    started, body = False, []
    for ln in lines:
        if "SELFTEST-BEGIN" in ln:
            started, body = True, []
        elif "SELFTEST-END" in ln and started:
            return body
        elif started:
            body.append(ln)
    return None


def pick_port(explicit):
    import serial.tools.list_ports
    if explicit:
        return explicit
    ports = list(serial.tools.list_ports.comports())
    xiao = [p for p in ports if "XIAO" in f"{p.description} {p.product or ''}"]
    usb = xiao or [p for p in ports if "usbmodem" in p.device]
    if len(usb) == 1:
        return usb[0].device
    print("\n  Serial ports:")
    for p in ports:
        print(f"    {p.device:<28} {p.description}")
    sys.exit("\n  Pick one with --port" if ports else "\n  No serial ports found.")


def read_report(port):
    """Ask for the report with 'T' and collect it. The LED cycles first."""
    import serial
    with serial.Serial(port, BAUD, timeout=1) as ser:
        time.sleep(0.5)
        ser.reset_input_buffer()
        print("  watch the XIAO's LED now: red, then green, then blue\n")
        ser.write(b"T")
        lines, t0, nudged = [], time.time(), False
        while time.time() - t0 < READ_TIMEOUT_S:
            raw = ser.readline()
            if not raw:
                # The board answers only after its 5 s BLE scan at boot.
                if not nudged and time.time() - t0 > 10:
                    ser.write(b"T")
                    nudged = True
                continue
            ln = raw.decode("utf-8", "replace").rstrip()
            lines.append(ln)
            if "SELFTEST-END" in ln:
                break
    return lines


def ask_led():
    while True:
        try:
            s = input("  Did red, green and blue each light up? (y/n): ").strip().lower()
        except EOFError:
            return None
        if s in ("y", "yes", "是"):
            return True
        if s in ("n", "no", "否"):
            return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", help="board id as written in the sheet, e.g. XIAO1")
    ap.add_argument("--tester", default="")
    ap.add_argument("--port")
    ap.add_argument("--list", action="store_true", help="list serial ports")
    ap.add_argument("--report", help="grade a saved report file instead of a board")
    ap.add_argument("--led", choices=["y", "n"], help="answer the LED question up front")
    ap.add_argument("--dry-run", action="store_true", help="write nothing")
    a = ap.parse_args()

    if a.list:
        import serial.tools.list_ports
        for p in serial.tools.list_ports.comports():
            print(f"  {p.device:<28} {p.description}")
        return
    if not a.id:
        sys.exit("  --id is required (which XIAO is this?)")

    if a.report:
        lines = Path(a.report).read_text(encoding="utf-8").splitlines()
    else:
        port = pick_port(a.port)
        print(f"\n  {a.id} on {port} @ {BAUD}")
        try:
            lines = read_report(port)
        except Exception as e:                  # serial errors, unplugged mid-read
            sys.exit(f"\n  cannot read {port}: {e}")

    body = between_markers(lines)
    if body is None:
        sys.exit("\n  No complete report. Either selftest.ino is not flashed, the port\n"
                 "  is wrong, or the board is still busy: unplug, plug in, try again.")
    for ln in body:
        print(f"    {ln}")
    rep = parse(body)

    saw = {"y": True, "n": False}.get(a.led) if a.led else ask_led()

    print("\n" + "=" * 66)
    steps, failed = {}, []
    for key, label, fn, gate in CHECKS:
        ok, why = fn(rep[key]) if key in rep else (None, "not reported by firmware")
        mark = "ok  " if ok else ("FAIL" if ok is False else "?   ")
        print(f"  [{mark}] {label:<18} {why}")
        steps[key] = {"ok": ok, "why": why, "raw": rep.get(key, {}).get("_raw", "")}
        if gate and ok is not True:
            failed.append(label)
    ok, why = check_led(saw)
    print(f"  [{'ok  ' if ok else 'FAIL' if ok is False else '?   '}] {'RGB LED':<18} {why}")
    steps["LED"] = {"ok": ok, "why": why}
    if ok is not True:
        failed.append("RGB LED")

    verdict = "PASS" if not failed else "FAIL"
    board_id = rep.get("ADDR", {}).get("id", "")
    print("=" * 66)
    print(f"  {a.id}: {verdict}" + (f"  ({', '.join(failed)})" if failed else ""))
    print(f"  8 功能 Function (column S): {'Y' if verdict == 'PASS' else 'N'}")
    if board_id:
        print(f"  board id {board_id}   <- unique per XIAO, worth noting in the sheet")

    if a.dry_run:
        print("\n  dry run: nothing written\n")
        return
    with RESULTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"),
                            "id": a.id, "model": MODEL, "tester": a.tester,
                            "verdict": verdict, "failed_step": 8 if failed else None,
                            "summary": "; ".join(failed), "board_id": board_id,
                            "steps": {f"8_function_{k}": v for k, v in steps.items()}},
                           ensure_ascii=False) + "\n")
    print(f"  wrote {RESULTS.parent.name}/{RESULTS.name}\n")


if __name__ == "__main__":
    main()
