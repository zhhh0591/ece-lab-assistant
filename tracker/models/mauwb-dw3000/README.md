# MaUWB_DW3000 with STM32 AT Command — 10-board incoming inspection

Makerfabs SKU **MAUWBCA1**. PCB silkscreen **"ESP32 AT UWB Pro with Display v1.1"**.
ESP32-WROVER-B + STM32F103 + Qorvo DW3000. Superseded by the ESP32-S3 version, which
matters mostly because **most of the code you will find online is for the S3**.

```
ESP32-WROVER-B  --UART 115200-->  STM32F103  -->  DW3000 + PA/LNA  -->  antenna
   your sketch, WiFi/BT,            UWB controller: ranging, time slots,
   OLED, USB serial                 multi-anchor arbitration
```

Two MCUs. You do not write DW3000 drivers — you send the STM32 AT commands and it
reports distances back.

## Pin map (WROVER-B variant — verify against this before believing any failure)

| Function | This board | ESP32-S3 version |
|---|---|---|
| STM32 RESET | **GPIO 32** | 16 |
| UART2 RX (ESP32←STM32) | **18** | 18 |
| UART2 TX (ESP32→STM32) | **19** | 17 |
| I2C SDA | **4** | 39 |
| I2C SCL | **5** | 38 |

OLED SSD1306 128×64 at `0x3C`. STM32 link 115200 8N1.

## Three traps that will make a good board look dead

1. **Makerfabs' own `esp32_at.ino` ships with the S3 pins active** and the ESP32 pins
   commented out, despite the filename. Flash it unchanged on this board and the STM32
   never answers. Their `serial_test.ino` has the correct ESP32 pins.
2. **Arduino IDE → Tools → PSRAM must be "Enabled".** Left disabled,
   `ESP.getPsramSize()` returns 0 and every one of the ten boards reports a PSRAM
   failure. `selftest.py` says so explicitly rather than just failing.
3. **Board must be set to "ESP32 Dev Module"**, not any S3 board.

## Phase A — solo self-test  (built, works on one board)

```bash
./flash.sh                     # once per board -- build settings pinned in the script
python3 selftest.py --list
python3 selftest.py --id ECE-0101 --tester HZ
```

On an Apple-silicon Mac, Arduino's `ctags` (used to compile any new or changed sketch)
is an Intel binary. Without Rosetta the build stops with `bad CPU type in executable`;
an unchanged sketch only keeps building because its old result is cached. Fix:
`softwareupdate --install-rosetta`.

Checks ESP32 identity/cores, flash size, PSRAM, I2C bus, OLED init, the STM32 `AT?`
link, and a WiFi scan to exercise the 2.4 GHz chain. Writes PASS/FAIL into
`../../boards.csv` and the full report into `../../results.jsonl`.

The OLED test flashes all pixels white for ~1 s — **watch the screen**, dead rows and
columns only show against full white — then draws vertical stripes to expose stuck
columns.

It also prints the **MAC address**, which is a free per-board serial number. With ten
identical boards, that is how you prove you did not test number 3 twice.

**Not covered:** UWB ranging (needs two boards, phase B) and the battery charger.
Makerfabs' battery demo reads GPIO4, but on this variant GPIO4 is I2C_SDA, so that pin
is wrong here and the right one is undocumented — put a meter on the battery pads
instead of guessing.

## Phase B — ranging  (scripted; tested against a simulated board, not a real pair yet)

Ranging cannot be tested on one board. One board is the fixed reference (anchor A0);
every other board takes a turn as the tag (T0) against it.

```bash
./flash.sh bridge                                     # every board, for this phase
python3 ranging.py anchor --id ECE-0101               # once: make the reference
python3 ranging.py tag --id ECE-0102 --ref ECE-0101 --distance 2.00 --tester HZ
```

`bridge/bridge.ino` makes the ESP32 a wire between USB and the STM32, so `ranging.py`
sends the AT commands itself (Makerfabs AT Command Manual v1.1.2): `AT?`, `AT+RESTORE`,
`AT+SETCFG`, `AT+SETCAP`, `AT+SETRPT=1`, `AT+SAVE`, `AT+RESTART`, then reads the
settings back. Role and index are never compiled in, unlike Makerfabs' `esp32_at.ino`
— one firmware for all ten. Before configuring anything it asks the bridge for the
board's MAC and checks it against `boards.csv`; the wrong board on the port stops the run.

**Setup**

1. Reference anchor at one fixed spot for the whole batch: non-metallic support,
   **antennas at the same height**, clear line of sight, at least 1 m from walls and
   metal. Multipath will dominate anything you do on a cluttered lab bench and you
   will blame the board. After `ranging.py anchor` it can run from any USB charger —
   the role is saved in the module.
2. Tape-measure antenna to antenna, mark the tag's spot, and use the same mark and
   orientation for every board.
3. Power only the anchor and the board under test. Every board under test is T0.

**What PASS means:** at least 10 distances to A0 in the 15 s window — the board ranges.
That is the only gate. The offset (reported − tape) is recorded and printed beside the
other boards measured against the same reference, but never judged: these boards read
about half a metre long until calibrated (the review below measured 50–61 cm), and that
is a calibration number, not a fault.

A FAIL with **no reports at all** is most often the anchor being off or out of reach,
and the script says so. Check the anchor and re-run; a passing re-run clears the
script's own entry in `boards.csv` (it never touches the self-test's entries).

**Firmware differences it handles.** The range line changed between firmware versions:
older ones end with `rssi:(...)` and slot *i* is anchor *i*; v1.1.6 ends with
`ancid:(...)` and any slot can hold any anchor. `AT+SETCAP` took 2 fields before
v1.1.1 and 3 after, so the script asks `AT+GETCAP?` first and answers in the same shape.

**Not confirmed on hardware yet**, so the first real pair tests the test, the way board
1 did for the self-test: how long the module needs after `AT+RESTORE` and `AT+RESTART`,
whether a tag with no anchor in reach prints empty reports or nothing, and whether the
module echoes commands. If the first good board FAILs, suspect the script first.

Every run, with all its raw readings, goes to `../../ranging.jsonl` (gitignored — it
is lab equipment data).

## Phase C — calibration

The honest situation: repeatability is excellent (published measurements put the
position DRMS around 1–3 cm), but **absolute distance carries a per-board offset** that
can be tens of centimetres. An independent review of this exact board fitted
`actual = m × reported + b` and got m ≈ 1.0089, b ≈ −61.2 — a large constant term.

So: measure each board at several known distances (50 cm, 1 m, 2 m, 3 m, 5 m), fit a
line, store `m` and `b` per board. One `ranging.py tag` run per distance collects the
data; `ranging.jsonl` keeps every reading for the fit.

**The caveat that matters:** the offset belongs to the *pair*, not to one board — both
antenna delays add. Two honest options:

- **Reference-board method (practical).** Pick one board as the reference and calibrate
  the other nine against it. Fast, and fine as long as you always deploy with this set,
  but it folds the reference's own delay into all nine numbers.
- **Round-robin (correct).** Measure all pairs at known distances and least-squares
  solve for individual per-board delays. With 10 boards that is 45 pairs — right, but
  expensive by hand.

Start with the reference method. Write down that you did, so nobody later mistakes
those coefficients for absolute antenna delays.

## Running all ten

1. Flash `selftest.ino` to all ten first, in one sitting. Same IDE settings for all —
   settings drift between sessions is a real source of fake failures.
2. Label them `ECE-0101`..`ECE-0110` (or whatever the lab scheme turns out to be) and
   record the MAC each one reports.
3. `selftest.py --id ...` on each. ~30 s per board.
4. `python3 ../../analyze.py` — with ten identical boards, a repeated signature is a
   batch problem worth chasing, not ten coincidences.
5. Phase B on the survivors: `./flash.sh bridge` on each, `ranging.py anchor` once on
   the reference, then `ranging.py tag` on each of the others from the same mark.

**Scaling note:** since the interface is USB, a powered 10-port hub tests all ten in
one pass without touching anything. That is the whole fixture. No pogo pins.
