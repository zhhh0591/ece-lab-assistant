# Using a multimeter

My notes from SparkFun's How to Use a Multimeter and EEVblog #1636.

## Setting it up

- The dial picks what to measure: DC volts, AC volts, resistance, continuity,
  diode test, or current.
- The black lead always goes in COM. The red lead goes in VΩ for everything
  except current.
- Current has its own jacks, mA for small currents and 10A for large ones.
  SparkFun uses 10A when the current might be over 200 mA.
- A reading of 1 or OL means the value is over the range.

## Voltage

- Measure with the power on, one probe on each point, so the meter is in
  parallel with the part.
- Swapped leads only show a minus sign. Nothing is damaged.
- Pick a range higher than the voltage you expect.

## Resistance

- Measure with the power off. The meter sends its own small current, so power
  in the circuit gives a wrong reading and can damage the meter.
- Take the part out, or lift one leg. Other parts in the circuit change the
  reading. In EEVblog's video a 10 kΩ resistor read 3.6 kΩ in circuit and
  10 kΩ with one leg lifted.
- The leads add about 0.1 to 1 Ω. For small values, press the probes firmly or
  zero the leads with REL.

## Current

- Break the circuit and put the meter in series, with the red lead in the mA
  or 10A jack.
- The current jack is close to a short, about 0.2 Ω on EEVblog's meter. Never
  connect it across a supply. At best it blows the fuse inside the meter.
- Move the red lead back to VΩ when done. If it stays in the current jack, the
  next voltage measurement is a short.
- The meter shows the average current. Fast spikes need an oscilloscope.

## Continuity and diodes

- Continuity mode beeps when two points are connected. Use it with the power
  off. SparkFun used it to find which wire in a headphone cable goes to which
  part of the plug. A good meter beeps fast enough to catch a probe sliding
  across pins.
- Diode mode: red on the anode, black on the cathode, the end with the band. A
  silicon diode reads about 0.5 to 0.6 V (0.57 V in SparkFun's video). The
  other way round shows OL. Many meters can light an LED this way.

## Safety

- Mains needs a meter rated CAT III or higher with ceramic HRC fuses, used with
  one hand. 3.3 V and 5 V boards do not.
- Buy a meter with a UL or ETL safety mark.
- Take alkaline batteries out of a meter that will not be used for a long
  time, or they can leak.

## Probes

Standard probes, fine tips for small pins, alligator clips that hold on by
themselves, IC hooks for chip legs, and tweezers for surface-mount parts.
