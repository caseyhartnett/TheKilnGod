# TheKilnGod Controller Board Spec (v1)

## Scope

This spec is based on the current codebase defaults in `config.py` and is intended for a cleaner, professional PCB replacing hand-wired prototyping.

Primary target: Raspberry Pi 3/Zero 2 W as host computer, with external kiln power switching via SSR.

## Design Goals

- Keep compatibility with current software defaults
- Support Adafruit thermocouple breakout boards (MAX31855/MAX31856)
- Provide simple, reliable 5V relay-control output wiring
- Provide 5V fan output for SSR heatsink cooling
- Improve electrical robustness and serviceability

## Software-Pinned Defaults (from current code)

- `gpio_heat` (relay control): BCM 7 (header pin 26), active-low by default (`gpio_heat_invert = True`)
- Thermocouple software SPI defaults:
  - `spi_sclk`: BCM 23 (pin 16)
  - `spi_miso`: BCM 21 (pin 40)
  - `spi_cs`: BCM 24 (pin 18)
  - `spi_mosi`: BCM 19 (pin 35) (not used by MAX31855, present in code path)
- I2C display:
  - SDA: BCM 2 (pin 3)
  - SCL: BCM 3 (pin 5)
  - Address default: `0x3C`

## Board-Level Architecture

- Raspberry Pi 40-pin HAT-style or cable-connected controller board
- Low-voltage control board only (no mains traces on this PCB recommended)
- External SSR switches mains to kiln
- Optional onboard fan control transistor (for 5V fan)
- Optional OLED header for local status display

## Required Connectors

### 1) Raspberry Pi Interface

- 40-pin header footprint (2x20)
- Include clear silkscreen for:
  - 5V
  - 3.3V
  - GND
  - BCM pin mapping for used signals

### 2) Thermocouple Breakout Connector (Adafruit MAX31855/MAX31856)

Use a keyed 6-pin JST-XH or pluggable terminal:

- 3V3
- GND
- SCK
- CS
- SO/MISO
- SI/MOSI (optional pass-through for compatibility)

Notes:
- Most MAX breakout boards run at 3.3V logic; keep logic at 3.3V.
- Add local decoupling (0.1uF + 1uF near connector).

### 3) SSR Control Output (5V-compatible switching output)

Provide a 2-pin pluggable terminal block:

- `SSR+` (switched output)
- `SSR-` (GND return)

Implementation recommendation:
- Use NPN transistor or N-MOSFET low-side driver from `gpio_heat`.
- Include:
  - Base/gate resistor
  - Pull-down resistor on gate/base
  - Indicator LED + resistor
- Driver should sink at least 20-30mA for common SSR inputs.

Reason:
- Pi GPIO alone can be marginal for some SSR input currents.
- Matches behavior already noted in project docs.

### 4) 5V Fan Output (for SSR heatsink cooling fan)

Provide a 2-pin or 3-pin fan header:

- `FAN+` (5V)
- `FAN-` (switched GND or direct GND)
- optional tach pin (future)

Two options:
- v1 simple: always-on 5V fan output
- v1.1 better: MOSFET-switched fan output from spare GPIO

If MOSFET-switched, suggest default spare GPIO:
- BCM 25 (pin 22) or BCM 12 (pin 32), configurable later in software

### 5) OLED Display Header (SSD1309 I2C)

4-pin header:

- 3V3 (or 5V only if module requires it; most logic still I2C-safe)
- GND
- SDA (BCM 2)
- SCL (BCM 3)

### 6) Auxiliary I/O Header (future-proof)

Expose at least 4 spare GPIO + GND + 3V3 for:

- Door interlock switch
- Emergency stop input
- Buzzer
- Stack light

## Power Inputs and Protection

### 5V Input Strategy

Preferred:
- Power Raspberry Pi through official method (USB-C/micro-USB depending model)
- Derive board 5V from Pi 5V rail only for light peripherals

If powering fan/SSR input from board 5V:
- Include polyfuse on fan rail
- Add reverse-polarity protection (ideal diode or Schottky)
- Add TVS diode on 5V input rail

### 3.3V Rail

- Use Pi 3.3V for logic-level signals only
- Avoid heavy load from 3.3V pin

### Grounding

- Star/controlled grounding between:
  - Pi logic ground
  - Thermocouple ground
  - SSR/fan return currents
- Keep thermocouple digital lines away from fan/relay switching currents

## Signal Conditioning and EMI Practices

- Add RC filtering option footprints on thermocouple SPI lines (DNP by default)
- Keep SPI traces short and routed together
- Add test points for:
  - 5V
  - 3.3V
  - GND
  - `gpio_heat`
  - `spi_sclk`, `spi_miso`, `spi_cs`
- Add status LEDs:
  - Power 5V
  - Power 3.3V
  - Heat command active
  - Fan active (if switched)

## Safety and Industrialization Features To Add

These are the most valuable additions beyond your current wiring:

1. Door/interlock input (dry contact)
- Hardware terminal + pull-up/down + RC debounce footprint.
- Software can later prevent run if interlock open.

2. Hardware emergency-stop input
- Latching input terminal (normally-closed loop preferred).
- Can cut SSR command path in hardware (recommended), not just software.

3. Thermal protection around SSR compartment
- Input for a local temperature sensor near SSR heatsink (future ADC/I2C).
- Enables fan control and overtemp alarm.

4. Watchdog heartbeat output/input
- Optional pin to support external hardware watchdog or supervisor.

5. Field wiring quality
- Screw/pluggable terminal blocks with labeling:
  - Thermocouple
  - SSR out
  - Fan out
  - Interlocks

## What You Asked For (Checklist)

- Adafruit thermocouple converter support: Yes (MAX31855/MAX31856 connector included)
- 5V on/off switching output for relay: Yes (transistor/MOSFET SSR driver output)
- Output for large 5V cooling fan: Yes (always-on or GPIO-switched)
- Extra recommended pieces: Yes (interlock, e-stop path, power protection, test points, status LEDs)

## Components (Starter BOM Guidance)

- GPIO output driver for SSR:
  - 1x logic-level N-MOSFET (or NPN transistor)
  - 1x gate/base resistor
  - 1x pull-down resistor
  - 1x LED + resistor
- Fan driver (if switched):
  - 1x logic-level N-MOSFET sized for fan current
  - 1x flyback diode (for brushed DC fans if needed)
  - 1x gate resistor + pull-down
- Protection:
  - TVS diode for 5V rail
  - Polyfuse on fan/output rail
  - Reverse-polarity protection device
- Connectors:
  - 2x20 Pi header
  - Pluggable terminals for SSR/fan/interlocks
  - JST-XH or equivalent for thermocouple breakout
  - 4-pin OLED header

## PCB Layout Guidance

- 2-layer board is sufficient
- Keep low-noise sensor section separated from switched outputs
- Wide traces for fan/SSR drive current return paths
- Silkscreen every connector with function + polarity
- Mounting holes aligned for enclosure standoffs

## Software Compatibility Notes

v1 board works with current software if:

- Pin mapping remains at current defaults in `config.py`
- `gpio_heat_invert` remains set correctly for chosen driver polarity
- Fan is always-on, or software update later adds `gpio_fan` support

## Suggested v1.1 Software Enhancements (small)

1. Add `gpio_fan` config option with simple logic:
- fan on when heating or when SSR-temp/interlock policy requests it

2. Add `gpio_interlock` input:
- prevent starting profile if open
- abort/pause run if opened mid-cycle (configurable)

3. Add `gpio_estop` input:
- immediate abort and latched fault state

## Final Recommendation

For first professional board spin:

- Keep mains switching physically off-board via external SSR + proper enclosure
- Implement robust 5V SSR driver and fan output on this controller board
- Add interlock/e-stop terminals now, even if software uses them later

That gives you a clean, production-looking board with minimal software disruption and a clear path to safer next revisions.

