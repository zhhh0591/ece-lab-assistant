# MaUWB_DW3000 test tools

Makerfabs SKU MAUWBCA1, silkscreen "ESP32 AT UWB Pro with Display v1.1".
An ESP32-WROVER-B runs our code and sends AT commands over serial to an
STM32F103, which runs the Qorvo DW3000 UWB radio and reports distances back.

```
ESP32-WROVER-B  --UART 115200-->  STM32F103  -->  DW3000 + PA/LNA  -->  antenna
```

Most code online is for the newer ESP32-S3 version, which uses different pins.

## Once per Mac

- arduino-cli with the `esp32:esp32` board package, and `pip install pyserial`.
- Apple silicon only: if a build stops with `bad CPU type in executable`, run
  `softwareupdate --install-rosetta`.

## Test 1: self-test, one board at a time

1. Plug the board into the Mac with a data cable.
2. Flash the self-test, once per board:
   ```bash
   ./flash.sh
   ```
3. Run it:
   ```bash
   python3 selftest.py --id MAUWB-001 --tester HZ
   ```
4. Watch the OLED: it goes all white for about 1 s, then shows stripes. A dark
   row or column means a bad screen.
5. Read the result: one line per check, then PASS or FAIL, then the MAC.

| Check | What it proves |
|---|---|
| ESP32 | the right chip (WROVER-B, 2 cores) |
| Flash | at least 4 MB |
| PSRAM | 4 MB (the module has 8 MB; the ESP32 can only map 4 MB) |
| I2C, OLED | the screen answers at 0x3C and starts up |
| STM32 | it answers `AT?`, so the UWB side is alive |
| WiFi | a scan finds networks, so the 2.4 GHz antenna works (a note, not a fail) |

Not covered: UWB ranging (Test 2) and the battery charger.

## Test 2: ranging, two boards

One board stays put as the reference (anchor); every other board takes a turn
as the tag. Run the self-test first: ranging checks each board's MAC.

1. Flash every board with the bridge firmware:
   ```bash
   ./flash.sh bridge
   ```
2. Set up the reference board once:
   ```bash
   python3 ranging.py anchor --id MAUWB-001
   ```
   Put it on a non-metal stand, antenna at the same height as the tag's, at
   least 1 m from walls and metal. After this it can run from any USB charger.
3. Tape-measure antenna to antenna, mark the tag's spot, and use the same mark
   and the same direction for every board. Only the anchor and the board under
   test are powered.
4. Test each other board:
   ```bash
   python3 ranging.py tag --id MAUWB-002 --ref MAUWB-001 --distance 2.00 --tester HZ
   ```

PASS means at least 10 distances in 15 s. The distance error is written down
but not judged: these boards read about 50 to 60 cm long until calibrated. No
reports at all usually means the anchor is off or out of reach.

## Test 3: calibration, later

Measure each board at 0.5, 1, 2, 3 and 5 m (one `ranging.py tag` run each)
and fit `actual = m × reported + b` per board. The error belongs to the pair,
not one board, so calibrate all of them against the same reference board, and
write down that you did.

## Recording

- Steps 1 to 7 of the Test Procedure (meter, supply, visual, short, power-up,
  temperature, voltages) are done by hand and go straight into the board's row
  of the sheet.
- After Test 1, fill column S, "8 Function": Y for PASS, N for FAIL. Put the
  MAC in the notes. It is the only way to tell ten identical boards apart.
- The scripts also save every run by themselves: `selftest.py` to
  `../../boards.csv` and `../../results.jsonl`, `ranging.py` to
  `../../ranging.jsonl`. These files stay on the Mac and are not uploaded.

## If something looks wrong

Three things make a good board look dead:

1. Makerfabs' `esp32_at.ino` has the S3 pins switched on. Flashed unchanged,
   the STM32 never answers. Use these pins:

   | Function | This board | ESP32-S3 version |
   |---|---|---|
   | STM32 reset | GPIO 32 | 16 |
   | ESP32 receives from STM32 | 18 | 18 |
   | ESP32 sends to STM32 | 19 | 17 |
   | I2C SDA | 4 | 39 |
   | I2C SCL | 5 | 38 |

2. PSRAM must be Enabled in the build. If it is off, every board reports 0
   bytes. `flash.sh` sets it, so always flash with `flash.sh`.
3. The board type must be "ESP32 Dev Module", not an S3 board.

More:

- Battery charger: Makerfabs' demo reads GPIO4, but on this board GPIO4 is
  I2C SDA. Measure the battery pads with a meter instead.
- To find where a failing board breaks, use [`scope-card.html`](scope-card.html):
  four oscilloscope checks (3.3 V rail, the ESP32 to STM32 serial line, the
  STM32 reset line, the I2C bus). Sending `T` in the serial monitor reruns the
  self-test so the scope has something to catch.
- Ranging has only been tried on a simulated board. If the first real good
  board fails, suspect the script first.
- The ranging script handles both STM32 firmware versions (older ones end each
  line with `rssi:`, v1.1.6 with `ancid:`).

## All ten boards

1. Flash and self-test all ten in one sitting, about 30 s each.
2. Name them MAUWB-001 to MAUWB-010 and note each MAC.
3. Run `python3 ../../analyze.py`. Three boards failing the same way is a batch
   problem, not three coincidences.
4. Run Test 2 on the ones that passed.

A powered USB hub can hold all ten at once.

## Details

- OLED: SSD1306, 128×64, at I2C address 0x3C. ESP32 to STM32: 115200 baud, 8N1.
- `bridge.ino` turns the ESP32 into a wire between USB and the STM32, so
  `ranging.py` sends the commands itself (Makerfabs AT Command Manual v1.1.2):
  `AT?`, `AT+RESTORE`, `AT+SETCFG`, `AT+SETCAP`, `AT+SETRPT=1`, `AT+SAVE`,
  `AT+RESTART`, then reads the settings back. Role and index are set by the
  script, so one firmware serves all ten boards.
- `AT+SETCAP` takes 2 fields before firmware v1.1.1 and 3 after; the script asks
  `AT+GETCAP?` first and answers in the same form. In older firmware slot *i*
  is anchor *i*; in v1.1.6 any slot can hold any anchor.
- Still unknown until a real pair runs: how long the module needs after
  `AT+RESTORE` and `AT+RESTART`, whether a tag with no anchor prints empty
  reports or nothing, and whether the module echoes commands.
- A passing ranging re-run clears `ranging.py`'s own FAIL in `boards.csv`; it
  never touches the self-test's entries.
- Calibration numbers: repeatability is about 1 to 3 cm. An independent review
  of this board fitted m ≈ 1.0089 and b ≈ −61.2 cm. The more correct but slower
  alternative to one reference board is to measure all 45 pairs and solve for
  each board's delay by least squares.
