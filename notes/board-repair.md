# Finding a fault on a dead board

My notes from Adamant IT's Board Repair Basics #1 and #9. Both repair laptop
motherboards, but the method fits any board.

## How to think about a board

A board is many small circuits joined together, mostly power rails and data
lines. A missing voltage or a missing signal anywhere can stop the whole board.

## Tools

- A multimeter with fine-tip probes is enough to start.
- A soldering iron heats one point. Hot air heats an area, so it can melt the
  solder on many pins at once.

## Documents

- The schematic, a PDF, shows how the circuits connect.
- The boardview, a .brd file opened with the free OpenBoardView, shows where
  each part sits on the board.
- The part's designator links the two. Click a capacitor in the boardview, read
  C7408, then search the schematic for C7408.

The first letter of a designator gives the part type: R resistor, C capacitor,
L inductor, Q transistor or MOSFET, U chip, F fuse. D for diode and J for
connector are also common.

## Without a schematic

- Learn the patterns. A large inductor next to a few MOSFETs, often with a
  controller chip, is a buck converter, so that area is a power supply. Bigger
  MOSFETs mean that supply carries more current, like the one for the CPU.
- Follow the power from the input. On the laptop in the video it went from the
  DC jack through a fuse and inductors to a MOSFET switch, then through a
  current sense resistor to the main rail that feeds every other supply. The
  power stopped at the switch, because the main rail was shorted to ground.

## Order of checks

1. Look for burns, swollen parts, or liquid damage.
2. With the power off, measure each rail's resistance to ground. Close to 0 Ω
   means a short.
3. If there is a short, find the part causing it. One way is power injection:
   feed a limited current into the rail and look for the part that heats up.
4. If there is no short, power the board with a current limit and follow the
   power, measuring the voltage at each step.
5. Replace or remove the bad part.

Hot air, soldering, and power injection can burn me or damage a board. On lab
boards I will ask the technician first.
