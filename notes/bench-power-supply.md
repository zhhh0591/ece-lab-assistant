# Bench power supplies and current limiting

My notes from element14's Instrument Basics: Bench Power Supplies and UNSW's
lab video on current limiting.

## Ohm's law

V = I × R, so current is voltage divided by resistance. 2 V across 3.3 Ω gives
about 0.61 A. Power is P = V × I, and it turns into heat.

## The front panel

- The voltage knob sets the output voltage. The current knob sets the current
  limit.
- The meters show what is actually coming out. With the output off and nothing
  connected, the current reads 0 no matter where the knob is. Some models show
  the settings instead.
- A separate OUTPUT button lets me set everything before the board gets power.
  element14 names this and the current limit as the two features to look for.
- CV and CC lights show which mode the supply is in.
- There are three terminals: positive, negative, and a green GND. GND is earth
  from the wall socket, not the negative output. The outputs float, so a
  board's ground goes to the negative terminal.

## Constant voltage and constant current

The supply holds the set voltage (CV) while the load draws less than the limit.
If the load wants more, the supply lowers the voltage until the current equals
the limit (CC).

UNSW's example uses a 3.3 Ω resistor with a 1 A limit:

- Set to 2 V, it draws 0.61 A. That is under the limit, so the supply stays in
  CV.
- Set to 5 V, it would draw 1.5 A. The supply switches to CC, holds 1 A, and
  the output drops to about 3.3 V.

## Setting the limit before connecting a board

1. Turn the output off, with nothing connected.
2. Clip the positive and negative leads together.
3. Turn the output on and set the current knob to the limit, for example
   100 mA.
4. Turn the output off.
5. Unclip the leads and connect the board, checking which side is positive.
6. Turn the output on and watch the current. If CC lights up, turn it off.

Shorting the leads is safe here. The current is held at the limit and the
voltage is near 0 V, so the leads barely get warm.

In the element14 video, the limit is set low the first time a board gets
power, so a faulty board is less likely to burn.

## What CC means on a board

- CC as soon as the output turns on, with the voltage dropping, usually means a
  short. Turn it off and check the board.
- A limit that is too low causes its own problems. An ESP32 draws a burst of
  current when its WiFi starts. If the limit cuts that off, the voltage drops
  and the chip resets, which looks like a broken board.

## Two channels

Some supplies can join two channels. In series the voltages add. In parallel
the currents add, so two 2 A channels give 4 A. Turn the output off before
changing the mode.

Not every supply holds the current at the limit. Some shut the output off
instead, which element14 found when testing with an electronic load. A plain
resistor shows the limit most clearly.
