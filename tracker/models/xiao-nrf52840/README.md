# Seeed XIAO nRF52840: power breakout and self-test

The MaUWB_DW3000 has no 5 V pin; its 5 V is only reachable through its USB-C
port. So the current-limited bench supply reaches it through a XIAO:

```
E3647A +  ->  XIAO 5V pin  ->  XIAO USB-C  ->  C-to-C cable  ->  MaUWB
E3647A -  ->  XIAO GND pin
```

Never have the XIAO on the bench supply and on a computer at the same time.
The supply would push current back into the computer's USB port.

## Once per Mac

```bash
arduino-cli core install Seeeduino:nrf52 --additional-urls https://files.seeedstudio.com/arduino/package_seeeduino_boards_index.json
pip install pyserial
```

This is the "Seeed nRF52 Boards" package, not the mbed one.

## Self-test (step 8, "Function")

1. Take the bench supply off the XIAO. Plug the XIAO into the Mac with a data
   cable.
2. Flash the self-test, once per XIAO:
   ```bash
   ./flash.sh
   ```
   For a Sense board: `FQBN=Seeeduino:nrf52:xiaonRF52840Sense ./flash.sh`.
   If it says `Timed out waiting for acknowledgement`, press the XIAO's reset
   button twice quickly and run it again.
3. Wait about 6 s. The XIAO scans for Bluetooth devices when it starts.
4. Run the test with the right name for this board:
   ```bash
   python3 selftest.py --id XIAO1 --tester HZ
   ```
5. Watch the LED: red, then green, then blue. Answer y or n.
6. Read the result: one line per check, PASS or FAIL, and the board id.

| Check | What it proves |
|---|---|
| Chip | it is an nRF52840 and runs the test |
| Board id | not judged; a unique number burned in at the factory |
| USB 5 V | the chip sees 5 V from USB |
| 3.3 V | the 3.3 V regulator, measured by the chip itself, 3.3 V ±5 % |
| 32 MHz | the 32 MHz crystal runs |
| 32.768 kHz | that clock runs (see the note below) |
| Bluetooth | it hears at least one Bluetooth device in 5 s |
| LED | red, green and blue each light |

## Steps 1 to 7, by hand

Put the XIAO on a breadboard with a red jumper in its 5V row and a black one in
its GND row. Clip the supply onto the jumpers, never onto the pins: 3V3 is the
next pin over. Set the supply to 5.000 V and 0.200 A.

One number matters later: the tare, the XIAO's own current, which you subtract
from every MaUWB reading made through it. The supply's current display can be
off by up to ±(0.15% + 5 mA) (E364xA User's and Service Guide, Table 7-2), so
first read it with nothing connected and subtract that too.

## Recording

- Steps 1 to 7 go straight into the XIAO's row of the sheet.
- After the self-test, fill column S, "8 Function": Y for PASS, N for FAIL. Put
  the board id in the notes.
- `selftest.py` also saves every run to `../../results.jsonl` on the Mac. If you
  typed the wrong `--id`, the board id in that record shows which XIAO it was.

## Results so far

| | 5V to GND | Tare | 5V row | 3V3 row | Self-test |
|---|---|---|---|---|---|
| XIAO1 | 89.17 kΩ, climbing | 7 to 10 mA | 4.995 V | 3.3102 V | PASS |
| XIAO2 | 85.67 kΩ, climbing | 2 to 4 mA | 4.990 V | 3.301 V | PASS |

Each board's id is in the sheet, not here.

The tares differ, most likely because each board had a different program on it
when measured.

## Notes

- Why the 5V pin works: in Seeed's schematic (v1.1 Sense, v1.2 plain) the
  header's pin 14 carries the same VBUS label as the USB-C connector, with no
  part in between. The diode D1 sits only on the branch to the XIAO's own
  regulator, so the MaUWB's current never goes through it.
- `flash.sh` builds from a copy in a temp folder, because the Seeed package
  hands the sketch folder to the compiler without quotes and the space in
  "eece job" breaks the build.
- The first real board found a bug in the test: the Bluetooth library drives
  the blue LED by itself, so the LED check failed. Fixed with
  `Bluefruit.autoConnLed(false)`.
- The 32.768 kHz clock reads `src=rc` on both boards, although the board
  package asks for the crystal. Probably read before the crystal finished
  starting; not judged for now.
- Both boards show up as "Seeed XIAO nRF52840 Sense" on USB, but that name comes
  from the firmware. Whether they are Sense boards is not confirmed yet.
