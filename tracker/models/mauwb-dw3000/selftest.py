#!/usr/bin/env python3
"""
Incoming inspection for MaUWB_DW3000 boards (Makerfabs MAUWBCA1).

    python3 selftest.py --list
    python3 selftest.py --id ECE-0101
    python3 selftest.py --id ECE-0101 --port /dev/cu.usbserial-0001

Resets the board over USB, reads the self-test report the firmware prints,
grades it, and writes the verdict into ../../boards.csv plus the full raw
report into ../../results.jsonl.

Flash selftest/selftest.ino once per board first. After that this is the whole
test: plug in USB, run this, ~30 seconds.

The fixture for this board is a USB cable. It has two MCUs and a serial
console -- it can test itself, so there is nothing to build.

NOT covered here, on purpose:
  - UWB ranging. Physically impossible with one board; needs a pair.
    See RANGING in README.md -- that is phase B.
  - Battery charge circuit. Makerfabs' battery demo reads GPIO4, but on the
    WROVER-B variant GPIO4 is I2C_SDA, so that pin is wrong for this board and
    the correct one is not documented. Measure Vbat with a meter instead of
    guessing an ADC pin.
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import serial
import serial.tools.list_ports

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from log import COLUMNS, read_rows, write_rows          # noqa: E402

HERE = Path(__file__).resolve().parent
TRACKER = HERE.parents[1]
RESULTS = TRACKER / "results.jsonl"
MODEL = "MaUWB_DW3000 (ESP32 AT UWB Pro with Display v1.1)"

BAUD = 115200
READ_TIMEOUT_S = 45

KV = re.compile(r"^([A-Z0-9]+)\s+(.*)$")
FIELD = re.compile(r"(\w+)=(\"[^\"]*\"|\S+)")


# ==========================================================================
# RULES. Pure: parsed report in, (ok, why) out. Same split as tracker/test.py.
# ==========================================================================

def check_chip(f):
    model = f.get("model", "")
    if not model:
        return False, "no chip id returned"
    if "S3" in model.upper():
        return False, f"{model} -- that is an ESP32-S3, not the WROVER-B this board uses"
    if "ESP32" not in model.upper():
        return False, f"unexpected chip {model!r}"
    if f.get("cores") != "2":
        return False, f"{model} reports {f.get('cores')} core(s), WROVER-B is dual core"
    return True, f"{model} rev{f.get('rev')} {f.get('cores')} cores @ {f.get('mhz')} MHz"


def check_flash(f):
    # real_bytes comes from the chip's JEDEC id. cfg_bytes is only what the
    # build was told; reported alongside because a mismatch means the sketch
    # was compiled for the wrong flash size, which is a real thing to catch.
    real = int(f.get("real_bytes", 0))
    cfg = int(f.get("cfg_bytes", 0))
    if real == 0:
        return False, f"could not read flash id (jedec={f.get('jedec', '?')})"
    if real < 4 * 1024 * 1024:
        return False, f"{real / 1048576:.0f} MB -- below the 4 MB minimum for this module"
    note = f"{real / 1048576:.0f} MB"
    if cfg and cfg != real:
        note += f" (built for {cfg / 1048576:.0f} MB -- harmless, but fix the FQBN)"
    return True, note


def check_psram(f):
    # The module carries 8 MB physical, but the original ESP32 can only map
    # 4 MB of external SPI RAM into its address space (more needs the himem
    # banking API), so 4 MB is what a HEALTHY board reports here. Demanding
    # 8 MB fails every good board -- which it did, on the first one tested.
    b = int(f.get("bytes", 0))
    if b == 0:
        # Overwhelmingly a build-config mistake, not dead silicon.
        return False, ("0 bytes. Almost always Arduino IDE > Tools > PSRAM left "
                       "Disabled -- set it to Enabled, reflash, retest before "
                       "believing this")
    if b < 4 * 1024 * 1024:
        return False, (f"{b / 1048576:.1f} MB -- expected 4 MB addressable; "
                       f"PSRAM is partly unreadable")
    return True, (f"{b / 1048576:.0f} MB addressable "
                  f"(module has 8 MB; ESP32 maps 4 MB without himem)")


def check_i2c(f):
    addrs = f.get("addrs", "")
    if "0x3c" not in addrs.lower():
        return False, f"OLED not on the bus (found: {addrs or 'nothing'})"
    return True, f"0x3C present (bus: {addrs})"


def check_oled(f):
    return (f.get("init") == "ok",
            "initialised" if f.get("init") == "ok" else "SSD1306 init failed")


def check_stm32(f):
    r = f.get("resp", "").strip('"')
    if not r:
        return False, ("no response to AT? -- STM32 dead, held in reset, or the "
                       "UART pins are wrong (S3 sketch flashed on a WROVER-B?)")
    return True, f'replied {r!r}'


def check_wifi(f):
    n = int(f.get("networks", 0))
    if n == 0:
        return False, "0 networks -- ESP32 RF path suspect (or you are in a shielded room)"
    return True, f"{n} networks, best {f.get('best_rssi')} dBm"


CHECKS = [
    ("CHIP",  "ESP32 identity",  check_chip,  True),
    ("FLASH", "flash",           check_flash, True),
    ("PSRAM", "PSRAM",           check_psram, True),
    ("I2C",   "I2C bus",         check_i2c,   True),
    ("OLED",  "OLED",            check_oled,  True),
    ("STM32AT", "STM32 / UWB link", check_stm32, True),
    ("WIFI",  "WiFi RF",         check_wifi,  False),   # advisory, not a gate
]


# ==========================================================================

def pick_port(explicit):
    ports = list(serial.tools.list_ports.comports())
    usb = [p for p in ports if "usb" in p.device.lower() or "USB" in (p.description or "")]
    if explicit:
        return explicit
    if len(usb) == 1:
        return usb[0].device
    print("\n  Serial ports:")
    for p in ports:
        print(f"    {p.device:<28} {p.description}")
    sys.exit("\n  Pick one with --port" if ports else "\n  No serial ports found.")


def parse(lines):
    out = {}
    for ln in lines:
        m = KV.match(ln.strip())
        if not m:
            continue
        key, rest = m.group(1), m.group(2)
        if key in ("SELFTEST", "MAC"):
            out.setdefault(key, {})["raw"] = rest
            continue
        out[key] = {k: v.strip('"') for k, v in FIELD.findall(rest)}
        out[key]["_raw"] = rest
    return out


def read_report(ser):
    """Hardware-reset via DTR/RTS, then collect until SELFTEST-END."""
    ser.setDTR(False); ser.setRTS(True)      # EN low
    time.sleep(0.15)
    ser.reset_input_buffer()
    ser.setRTS(False)                        # EN high -> boot
    lines, started, t0, nudged = [], False, time.time(), False

    while time.time() - t0 < READ_TIMEOUT_S:
        raw = ser.readline()
        if not raw:
            if not started and not nudged and time.time() - t0 > 6:
                ser.write(b"T")              # auto-reset may not be wired
                nudged = True
            continue
        ln = raw.decode("utf-8", "replace").rstrip()
        if "SELFTEST-BEGIN" in ln:
            started, lines = True, []
            print(f"    {ln}")
            continue
        if not started:
            continue
        if "SELFTEST-END" in ln:
            return lines
        print(f"    {ln}")
        lines.append(ln)
    return lines if started else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", help="board id, e.g. ECE-0101")
    ap.add_argument("--port")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--location", default="")
    ap.add_argument("--tester", default="")
    a = ap.parse_args()

    if a.list:
        for p in serial.tools.list_ports.comports():
            print(f"  {p.device:<28} {p.description}")
        return
    if not a.id:
        sys.exit("  --id is required (which board is this?)")

    port = pick_port(a.port)
    print(f"\n  {a.id} on {port} @ {BAUD}\n  resetting...\n")

    try:
        with serial.Serial(port, BAUD, timeout=1.5) as ser:
            lines = read_report(ser)
    except serial.SerialException as e:
        sys.exit(f"\n  cannot open {port}: {e}")

    if lines is None:
        sys.exit("\n  No SELFTEST-BEGIN seen. Either selftest.ino is not flashed,\n"
                 "  the port is wrong, or the board is not booting.")

    rep = parse(lines)

    print("\n" + "=" * 66)
    steps, failed = {}, []
    for key, label, fn, gate in CHECKS:
        if key not in rep:
            ok, why = None, "not reported by firmware"
        else:
            ok, why = fn(rep[key])
        mark = "ok  " if ok else ("FAIL" if ok is False else "?   ")
        print(f"  [{mark}] {label:<18} {why}")
        steps[key] = {"ok": ok, "why": why, "raw": rep.get(key, {}).get("_raw", "")}
        if ok is False and gate:
            failed.append(label)

    mac = rep.get("MAC", {}).get("raw", "")
    verdict = "FAIL" if failed else "PASS"
    print("=" * 66)
    print(f"  {a.id}: {verdict}" + (f"  ({', '.join(failed)})" if failed else ""))
    if mac:
        print(f"  MAC {mac}   <- unique per board, use it to catch mix-ups")
    print("  UWB ranging NOT tested -- needs a second board. See README phase B.")
    print("=" * 66 + "\n")

    # ---- into the tracker ------------------------------------------------
    rows = read_rows()
    by_id = {r["id"]: r for r in rows}
    row = by_id.get(a.id) or {c: "" for c in COLUMNS}
    row["id"] = a.id
    row["model"] = MODEL
    row["location"] = a.location or row.get("location", "")
    row["status"] = verdict
    row["last_tested"] = datetime.now().date().isoformat()
    row["tested_by"] = a.tester or row.get("tested_by", "")
    row["known_issues"] = "; ".join(
        f"{lbl}: {steps[k]['why']}" for k, lbl, _, g in CHECKS
        if g and steps[k]["ok"] is False) or ""
    row["notes"] = (f"MAC {mac}" if mac else row.get("notes", ""))

    if a.id in by_id:
        rows[rows.index(by_id[a.id])] = row
    else:
        rows.append(row)
    write_rows(rows)

    with RESULTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"),
                            "id": a.id, "model": MODEL, "tester": a.tester,
                            "verdict": verdict,
                            "failed_step": failed[0] if failed else None,
                            "summary": row["known_issues"],
                            "mac": mac, "steps": steps}, ensure_ascii=False) + "\n")
    print(f"  wrote {TRACKER.name}/boards.csv and {TRACKER.name}/results.jsonl\n")


if __name__ == "__main__":
    main()
