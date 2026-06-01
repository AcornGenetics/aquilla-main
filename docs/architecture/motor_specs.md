# Motor Subsystem Specs

## Overview
The motor subsystem is implemented in `aq_lib/motor_class.py` and uses
RPi GPIO to drive two stepper axes:

- `Drawer`: moves the cartridge drawer in/out.
- `Axis`: moves the optics axis across the six wells.

Each motor uses a stepper driver with enable, step, and direction pins plus a
home switch input. Motion control is synchronous and blocking (no threading).

## Control Classes

### `Motor`
- Initializes GPIO mode to BCM.
- Sets `EN_PIN`, `STEP_PIN`, and `DIR_PIN` as outputs.
- Sets `HME_PIN` as input.
- Tracks `position` in steps (relative to home).

Key methods:
- `home()`: if already at home, moves out 100 steps; then steps toward home
  for `home_steps` and zeroes `position` if the switch is hit.
- `move_w_home_flag(steps, step_delay)`: steps with a home switch stop.
- `move_wo_home_flag(steps, step_delay)`: steps without home switch stop.
- `move_abs_wo_home_flag(position, step_delay)`: moves to an absolute position
  (relative to home).

### `Drawer`
- Inherits `Motor`.
- `open()`: `home()` then `move_abs_wo_home_flag(open_steps)`.
- `read()`: `home()` then `move_wo_home_flag(read_steps)`.

### `Axis`
- Inherits `Motor`.
- Builds `positions` for 6 wells using `well_one` and `well_spacing`.
- `goto_position(N)`: moves to well `N` (0-based).

## GPIO Pin Mapping

### Drawer
- `EN_PIN`: 12
- `STEP_PIN`: 5
- `DIR_PIN`: 25
- `HME_PIN`: 24
- `DIR_BACK_STATE`: `LOW`
- `DIR_FORWARD_STATE`: `HIGH`

### Axis
- `EN_PIN`: 26
- `STEP_PIN`: 19
- `DIR_PIN`: 13
- `HME_PIN`: 16
- `DIR_BACK_STATE`: `HIGH`
- `DIR_FORWARD_STATE`: `LOW`

## Host Configuration Values

Values come from `config_files/host_config.json` and are keyed by hostname.

### `sn01`
- Drawer: `open_steps=4500`, `read_steps=151`, `home_steps=5000`,
  `step_multiplier=32`
- Axis: `home_steps=2500`, `step_multiplier=8`, `well_one=300`,
  `well_spacing=359`

### `sn02`
- Drawer: `open_steps=4500`, `read_steps=160`, `home_steps=5000`,
  `step_multiplier=32`
- Axis: `home_steps=2500`, `step_multiplier=8`, `well_one=300`,
  `well_spacing=355`

## Known Problems / Faulty Logic

1. `Motor.position` is a class variable, so all motor instances share the
   same position state, which corrupts tracking when `Axis` and `Drawer` are
   used together. Faulty line: `aq_lib/motor_class.py:18`.
2. `move_w_home_flag()` updates `position` incorrectly when the home switch
   is not hit and `steps` is negative. The code subtracts a negative value,
   which increases the position instead of decreasing it. Faulty lines:
   `aq_lib/motor_class.py:81` and `aq_lib/motor_class.py:84`.
3. `aq_lib/hw_api.py` contains a bare `def` statement, which is a syntax error
   and prevents the module from importing; motor API calls defined there are
   also left as `pass`, so the backend integration is incomplete. Faulty line:
   `aq_lib/hw_api.py:101`.
4. `move_abs_w_home_flag()` uses the home switch stop logic even when moving
   away from home; if the switch is stuck active, the move may stop instantly.
   Faulty lines: `aq_lib/motor_class.py:89` through `aq_lib/motor_class.py:91`.
5. `Drawer.open()` and `Drawer.read()` compute `ret` but never return it, so
   callers cannot reliably check move results. Faulty lines:
   `aq_lib/motor_class.py:146` through `aq_lib/motor_class.py:152`.
