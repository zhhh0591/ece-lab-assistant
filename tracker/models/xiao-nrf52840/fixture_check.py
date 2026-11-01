#!/usr/bin/env python3
"""
Fixture check for a Seeed XIAO nRF52840 used as a USB-C power breakout.

    python3 fixture_check.py
    python3 fixture_check.py --id XIAO1 --tester HZ
    python3 fixture_check.py --dry-run          # practice run, writes nothing

The MaUWB_DW3000 has no 5 V pin, so the bench supply reaches it through a XIAO:
supply -> XIAO 5V pin -> XIAO USB-C -> C-to-C cable -> MaUWB. In Seeed's
schematic the header's pin 14 carries the same VBUS net label as the USB-C
connector, with no part in between, so this works.

Before a XIAO is trusted with that job it has to show that nothing on it is
shorted, that it draws a small steady current of its own (the tare, subtracted
from every MaUWB reading later), and that its 5V row is really at the supply
voltage while its own 3.3 V regulator works.

The steps follow the Test Procedure sheet: 1 meter, 2 supply, 3 visual,
4 short, 5 power-up, 6 thermal, 7 voltages, 8 function, 9 wrap up. Step 8 is
left blank here: a breakout's function is proven when it powers a MaUWB.

Limits, and where each comes from
  short     > 10 ohm, or climbing      same 10 ohm rule as the board tests
  power-up  CV, under the 0.200 A limit set on the E3647A
  5V row    4.75 to 5.25 V             USB 2.0 VBUS range
  3V3 row   3.3 V +/- 5 %              default regulator tolerance in the tracker
The E3647A's front-panel current reading is good to +/-(0.15% + 5 mA)
(E364xA User's and Service Guide, Table 7-2), so a tare of a few mA is only
roughly known. It is small next to a MaUWB's current.

Writes one record to ../../results.jsonl and puts a row for the online sheet
(columns A to T of boards.example) on the clipboard, ready to paste into
column A of the board's row.
"""

import argparse
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRACKER = HERE.parents[1]
RESULTS = TRACKER / "results.jsonl"

MODEL = "Seeed XIAO nRF52840"
SUPPLY_V = 5.000
LIMIT_A = 0.200
SHORT_MIN_OHM = 10.0
VBUS_MIN, VBUS_MAX = 4.75, 5.25          # USB 2.0 VBUS
V33_NOM, V33_TOL_FRAC = 3.3, 0.05


# ==========================================================================
# THE RULES.  Numbers in, (ok, why) out. No input, no files.
# ==========================================================================

def check_short(ohms, climbed):
    """5V row to GND, power off."""
    if ohms == float("inf"):
        return True, "open (OL)"
    if ohms < SHORT_MIN_OHM and not climbed:
        return False, f"{fmt_ohm(ohms)} and pinned low: short (< {SHORT_MIN_OHM:g} ohm)"
    if ohms < SHORT_MIN_OHM:
        return True, f"{fmt_ohm(ohms)} but climbing: capacitors charging, not a short"
    return True, f"{fmt_ohm(ohms)}" + (", climbing" if climbed else "")


def check_power_up(mode, max_a):
    """Supply mode and the highest current seen in the first 10 s."""
    if mode == "CC":
        return False, "supply went into CC: something pulls more than the limit"
    if max_a >= LIMIT_A:
        return False, f"{max_a * 1000:g} mA reached the {LIMIT_A * 1000:g} mA limit"
    return True, f"CV, at most {max_a * 1000:g} mA"


def check_range(v, lo, hi, unit="V"):
    if lo <= v <= hi:
        return True, f"{v:g} {unit} (want {lo:g} to {hi:g})"
    return False, f"{v:g} {unit} is outside {lo:g} to {hi:g}"


def tare_ma(low_a, high_a, zero_a):
    """XIAO's own current, with the supply's no-load reading taken off."""
    return round((low_a - zero_a) * 1000), round((high_a - zero_a) * 1000)


def fmt_ohm(ohms):
    if ohms == float("inf"):
        return "OL"
    if ohms >= 1e6:
        return f"{ohms / 1e6:g}M"
    if ohms >= 1e3:
        return f"{ohms / 1e3:.2f}K"
    return f"{ohms:g}"


# ==========================================================================
# PARSING what gets typed at the bench: "89.17k", "OL", "4 mA", "3。301".
# ==========================================================================

def _clean(raw):
    return raw.strip().replace("。", ".").replace("，", ",").replace(" ", "")


def parse_ohms(raw):
    s = _clean(raw).upper().rstrip("Ω").removesuffix("OHM")
    if s == "OL":
        return float("inf")
    scale = {"K": 1e3, "M": 1e6}.get(s[-1:], 1)
    return float(s[:-1] if scale != 1 else s) * scale


def parse_amps(raw):
    s = _clean(raw).lower()
    if s.endswith("ma"):
        return float(s[:-2]) / 1000
    return float(s.removesuffix("a"))


def parse_volts(raw):
    return float(_clean(raw).lower().removesuffix("v"))


# ==========================================================================
# THE SEAM.  A person reads the instruments and types the numbers.
# ==========================================================================

class Abort(Exception):
    pass


def ask(prompt, parse=str):
    while True:
        try:
            raw = input(f"    {prompt}: ")
        except EOFError:
            raise Abort("input ended")
        try:
            value = parse(raw)
        except ValueError:
            print("      did not understand that, try again")
            continue
        return value, _clean(raw)


def yes(prompt):
    def parse(raw):
        s = _clean(raw).lower()
        if s in ("y", "yes", "是", "对"):
            return True
        if s in ("n", "no", "否", "不"):
            return False
        raise ValueError
    return ask(f"{prompt} (y/n)", parse)[0]


def head(n, title):
    print(f"\n  {n}  {title}")


# ==========================================================================
# THE SEQUENCE.  Steps 1-7 are gates: fail one and the run stops there.
# ==========================================================================

def run():
    steps, done = {}, {}

    def fail(n, why):
        return {"verdict": "FAIL", "failed_step": n, "summary": why,
                "steps": steps, "done": done}

    head(1, "万用表自检 Meter check")
    done["meter"] = yes("Fluke 45 self-check done today (leads ~0.2 ohm, OL, beep)")
    if not done["meter"]:
        return fail(1, "meter not checked today: do that first")

    head(2, "电源限流 Supply limit")
    done["supply"] = yes("E3647A CC check done today (shorted clips go to CC)")
    if not done["supply"]:
        return fail(2, "supply limit not checked today: do that first")
    if not yes(f"Supply set to {SUPPLY_V:.3f} V / {LIMIT_A:.3f} A, output OFF"):
        return fail(2, "supply not set")
    if not yes("XIAO's USB-C is empty, and it is the only board on the supply"):
        return fail(2, "XIAO plugged in elsewhere: never feed its 5V pin then")

    head(3, "目视 Visual")
    done["visual"] = yes("No damage, no solder bridges, headers straight")
    if not done["visual"]:
        return fail(3, "visual: damage found")

    head(4, "短路 Short (power off)")
    beeps = (yes("Continuity: red jumper to 5V pin beeps"),
             yes("Continuity: black jumper to GND pin beeps"),
             not yes("Continuity: red jumper to 3V3 pin beeps"))
    steps["4_jumpers"] = {"ok": all(beeps), "why": "rows checked with continuity"}
    if not all(beeps):
        return fail(4, "a jumper is in the wrong breadboard row")
    ohms, ohms_raw = ask("5V row to GND at 5 s, ohms (e.g. 89.17k or OL)", parse_ohms)
    climbed = yes("Was it climbing")
    ok, why = check_short(ohms, climbed)
    steps["4_short_VBUS"] = {"ok": ok, "why": why, "ohms": None if ohms == float("inf") else ohms}
    print(f"      -> {'ok' if ok else 'FAIL'}: {why}")
    if not ok:
        return fail(4, f"short on 5V: {why}")

    head(5, "上电 Power-up")
    zero, _ = ask("No-load reading: clips on nothing, output ON, amps", parse_amps)
    print("      now output OFF, clip the jumpers, hand on Output On/Off, output ON")
    mode = "CC" if yes("Did the CC lamp light") else "CV"
    low, _ = ask("Lowest current in 10 s, amps (e.g. 0.002)", parse_amps)
    high, _ = ask("Highest current in 10 s, amps (e.g. 0.004)", parse_amps)
    ok, why = check_power_up(mode, high)
    t_lo, t_hi = tare_ma(low, high, zero)
    steps["5_power_up"] = {"ok": ok, "why": why, "mode": mode, "no_load_a": zero,
                           "low_a": low, "high_a": high, "tare_ma": [t_lo, t_hi]}
    print(f"      -> {'ok' if ok else 'FAIL'}: {why}" + (f"; tare {t_lo}~{t_hi} mA" if ok else ""))
    if not ok:
        print("\n  !! OUTPUT OFF NOW.")
        return fail(5, why)

    head(6, "温度 Thermal (after 10 s, back of a finger)")
    hot = yes("Anything too hot to keep a finger on")
    done["thermal"] = not hot
    steps["6_thermal"] = {"ok": not hot, "why": "hot part found" if hot else "nothing hot"}
    if hot:
        return fail(6, "a part runs hot")

    head(7, "电压 Voltages (powered, meter on V DC)")
    v5, v5_raw = ask("5V row, volts", parse_volts)
    v33, v33_raw = ask("3V3 row via a third jumper, volts", parse_volts)
    tol = V33_NOM * V33_TOL_FRAC
    ok5, why5 = check_range(v5, VBUS_MIN, VBUS_MAX)
    ok33, why33 = check_range(v33, round(V33_NOM - tol, 3), round(V33_NOM + tol, 3))
    steps["7_rail_VBUS"] = {"ok": ok5, "why": why5, "v": v5, "raw": v5_raw}
    steps["7_rail_3V3"] = {"ok": ok33, "why": why33, "v": v33, "raw": v33_raw}
    print(f"      -> 5V {'ok' if ok5 else 'FAIL'}: {why5}")
    print(f"      -> 3V3 {'ok' if ok33 else 'FAIL'}: {why33}")
    if not (ok5 and ok33):
        return fail(7, why5 if not ok5 else why33)

    head(9, "收尾 Wrap up")
    done["wrap_up"] = yes("Output OFF and clips removed")

    return {"verdict": "PASS", "failed_step": None, "summary": "", "steps": steps,
            "done": done}


# ==========================================================================
# RECORDING.  results.jsonl keeps the evidence; the sheet row is for pasting.
# ==========================================================================

def sheet_row(board, tester, res):
    """Columns A to T of the boards.example sheet, tab separated."""
    s, d = res["steps"], res["done"]

    def yn(flag):
        return "" if flag is None else ("Y" if flag else "N")

    def step_ok(key):
        return yn(s[key]["ok"]) if key in s else ""

    p = s.get("5_power_up", {})
    tare = p.get("tare_ma")
    notes = ("USB-C breakout for MaUWB power-up"
             + (f"; tare {tare[0]}~{tare[1]} mA; no-load {p['no_load_a']:.3f} A" if tare else ""))
    v5, v33 = s.get("7_rail_VBUS"), s.get("7_rail_3V3")
    short = s.get("4_short_VBUS")
    cols = [
        board, MODEL, "", date.today().isoformat(), res["verdict"], res["summary"],
        tester, notes,
        yn(d.get("meter")), yn(d.get("supply")), yn(d.get("visual")),
        fmt_ohm(short["ohms"] if short["ohms"] is not None else float("inf")) if short else "",
        step_ok("4_short_VBUS"),
        f"{tare[0]}~{tare[1]}" if tare else "",
        step_ok("5_power_up"),
        yn(d.get("thermal")),
        f"5V {v5['raw']}; 3V3 {v33['raw']}" if v5 and v33 else "",
        yn(v5["ok"] and v33["ok"]) if v5 and v33 else "",
        "",                                   # 8 function: proven by powering a MaUWB
        yn(d.get("wrap_up")),
    ]
    return "\t".join(cols)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--id", help="board id as written in the sheet, e.g. XIAO1")
    ap.add_argument("--tester", help="your initials")
    ap.add_argument("--dry-run", action="store_true", help="write nothing")
    a = ap.parse_args()

    print(f"\n  {MODEL}: fixture check")
    try:
        board = a.id or ask("Board id (e.g. XIAO1)")[1]
        tester = a.tester or ask("Your initials")[1]
        res = run()
    except Abort as e:
        sys.exit(f"\n  stopped ({e}), nothing written")

    print("\n  " + "=" * 60)
    print(f"  {board}: {res['verdict']}"
          + (f" at step {res['failed_step']}: {res['summary']}" if res["failed_step"] else ""))
    print("  " + "=" * 60)

    row = sheet_row(board, tester, res)
    print("\n  Row for the sheet (columns A to T):\n  " + row.replace("\t", " | "))

    if a.dry_run:
        print("\n  dry run: nothing written\n")
        return

    with RESULTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"),
                            "id": board, "model": MODEL, "tester": tester,
                            "verdict": res["verdict"], "failed_step": res["failed_step"],
                            "summary": res["summary"], "steps": res["steps"],
                            "done": res["done"]},
                           ensure_ascii=False) + "\n")
    print(f"\n  wrote {RESULTS.parent.name}/{RESULTS.name}")
    try:
        subprocess.run(["pbcopy"], input=row.encode("utf-8"), check=True)
        print("  row copied: click column A of the board's row in the sheet and paste\n")
    except (OSError, subprocess.CalledProcessError):
        print("  (could not copy to the clipboard; copy the row above by hand)\n")


if __name__ == "__main__":
    main()
