#!/usr/bin/env python3
"""
Log one board's test result at the bench, without opening a spreadsheet.

    python3 log.py            # interactive: one board, ~20 seconds
    python3 log.py ECE-0042   # jump straight to that board

Enter accepts the value in [brackets]. Existing boards are shown first so you can
see what was recorded last time before you overwrite it. Writes boards.csv
atomically and keeps one .bak.
"""

import csv
import os
import shutil
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "boards.csv"
COLUMNS = ["id", "model", "location", "last_tested", "status",
           "known_issues", "tested_by", "notes"]

# single-key shortcuts so you are not typing "UNTESTED" at a bench
STATUS_KEYS = {
    "p": "PASS", "f": "FAIL", "u": "UNTESTED",
    "r": "REPAIRED", "x": "RETIRED",
}

# remembered between runs so you type your initials once per session
TESTER_FILE = HERE / ".last_tester"


def read_rows():
    if not CSV_PATH.exists():
        return []
    with CSV_PATH.open(newline="", encoding="utf-8-sig") as f:
        return [{c: (r.get(c) or "").strip() for c in COLUMNS}
                for r in csv.DictReader(f)]


def write_rows(rows):
    """Write via temp file + rename so an interrupted run cannot truncate the CSV."""
    if CSV_PATH.exists():
        shutil.copy2(CSV_PATH, CSV_PATH.with_suffix(".csv.bak"))
    tmp = CSV_PATH.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, CSV_PATH)


def ask(label, default=""):
    shown = f" [{default}]" if default else ""
    try:
        v = input(f"  {label}{shown}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\naborted, nothing written")
        sys.exit(1)
    return v or default


def ask_status(default):
    hint = "  ".join(f"{k}={v.lower()}" for k, v in STATUS_KEYS.items())
    while True:
        v = ask(f"status ({hint})", default).strip()
        if v.lower() in STATUS_KEYS:
            return STATUS_KEYS[v.lower()]
        if v.upper() in STATUS_KEYS.values():
            return v.upper()
        print(f"    ? use one of: {', '.join(STATUS_KEYS)}")


def main():
    rows = read_rows()
    by_id = {r["id"]: r for r in rows}

    board_id = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if not board_id:
        print(f"\n{len(rows)} boards on file. Ctrl-C to bail.\n")
        board_id = ask("board id")
    if not board_id:
        sys.exit("no id given, nothing written")

    cur = by_id.get(board_id)
    if cur:
        print(f"\n  existing record for {board_id}:")
        for c in COLUMNS[1:]:
            if cur[c]:
                print(f"    {c:<13} {cur[c]}")
        print("  Enter keeps each value.\n")
    else:
        print(f"\n  {board_id} is new.\n")
        cur = {c: "" for c in COLUMNS}
        cur["id"] = board_id

    last_tester = (TESTER_FILE.read_text().strip()
                   if TESTER_FILE.exists() else "")

    rec = dict(cur)
    rec["model"]        = ask("model", cur["model"])
    rec["location"]     = ask("location", cur["location"])
    rec["status"]       = ask_status(cur["status"] or "u")
    rec["known_issues"] = ask("known issues (plain english, be specific)",
                              cur["known_issues"])
    rec["notes"]        = ask("notes", cur["notes"])
    rec["tested_by"]    = ask("tested by", cur["tested_by"] or last_tester)

    # a real test happened => stamp today. UNTESTED must not carry a date.
    if rec["status"] == "UNTESTED":
        rec["last_tested"] = ""
    else:
        rec["last_tested"] = ask("date tested",
                                 date.today().isoformat())

    print("\n  about to write:")
    for c in COLUMNS:
        print(f"    {c:<13} {rec[c] or '-'}")
    if ask("\n  save? (y/n)", "y").lower() not in ("y", "yes"):
        sys.exit("not saved")

    if board_id in by_id:
        rows[rows.index(by_id[board_id])] = rec
        what = "updated"
    else:
        rows.append(rec)
        what = "added"

    write_rows(rows)
    if rec["tested_by"]:
        TESTER_FILE.write_text(rec["tested_by"])

    done = sum(1 for r in rows if r["status"] != "UNTESTED")
    print(f"\n  {what} {board_id}.  {done}/{len(rows)} boards tested.")
    print("  run  python3 build.py  to refresh the page.\n")


if __name__ == "__main__":
    main()
