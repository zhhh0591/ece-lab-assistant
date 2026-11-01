# Seeed XIAO nRF52840 as a USB-C power breakout

The MaUWB_DW3000 has no 5 V pin. Its 5 V rail is only reachable through its
USB-C port, so a current-limited bench supply cannot clip onto it directly. A
XIAO nRF52840 does the job:

```
E3647A +  ->  XIAO 5V pin  ->  XIAO USB-C  ->  C-to-C cable  ->  MaUWB
E3647A -  ->  XIAO GND pin
```

In Seeed's schematic (v1.1 Sense, v1.2 plain) the header's pin 14 carries the
same VBUS net label as the USB-C connector, with no part in between. The diode
D1 sits only on the branch to the XIAO's own 3.3 V regulator, so the MaUWB's
current never passes through it.

Never feed the 5V pin while the XIAO is plugged into a computer: the supply
would push current back into the computer's USB port.

## Check a XIAO before using it

```bash
python3 fixture_check.py --id XIAO1 --tester HZ
python3 fixture_check.py --dry-run            # practice, writes nothing
```

The XIAO sits on a breadboard with red and black jumpers in its 5V and GND
rows; the clips go on the jumpers, never on the pins, because 3V3 is the next
pin over. The script walks the steps of the Test Procedure sheet, asks for each
reading, stops at the first failure, and works out the tare: the XIAO's own
current, which is subtracted from every MaUWB reading made through it.

| Step | Pass when | Source |
|---|---|---|
| 4 Short, 5V row to GND, power off | over 10 ohm, or still climbing | same rule as the board tests |
| 5 Power-up at 5.000 V / 0.200 A | CV, under the limit | the limit set on the supply |
| 7 5V row, powered | 4.75 to 5.25 V | USB 2.0 VBUS range |
| 7 3V3 row, powered | 3.3 V +/- 5 % | default regulator tolerance in the tracker |

The E3647A's front-panel current reading is good to +/-(0.15% + 5 mA)
(E364xA User's and Service Guide, Table 7-2), so a tare of a few mA is only
roughly known. Read the supply with nothing connected first and the script
takes that reading off.

Each run adds one record to `../../results.jsonl` and copies a row for the
online sheet (columns A to T) to the clipboard.

## First two

| | 5V to GND | Tare | 5V row | 3V3 row |
|---|---|---|---|---|
| XIAO1 | 89.17 kΩ, climbing | 7 to 10 mA | 4.995 V | 3.3102 V |
| XIAO2 | 85.67 kΩ, climbing | 2 to 4 mA | 4.990 V | 3.301 V |

Same model, same readings except the tare. The likeliest reason is a different
program on each board, not a fault.
