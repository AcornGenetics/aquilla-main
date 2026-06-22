# Hardware Spec: [Subsystem Name]

**Status:** Draft 
**Author:** Jack Hu
**Last updated:** 2026-06-03
**Subsystem:** Motor
**Source file(s):** `state_run_assay.py`

---

## 1. Overview

As of current, the drawer of the SENTRI opens automatically when the device turns on. The purpose of this spec is to remove this feature so that the SENTRI drawer will not open automatically on device startup. 

---

## 2. Hardware Components

| Component | Part / Model | Interface | Notes |
|-----------|-------------|-----------|-------|
| Drawer stepper motor | (TBD — fill in part) | Step/Dir/Enable via GPIO + stepper driver | Drives the tray in/out. The auto-open outward move (`open_steps` = 4500) is what this change removes; the motor no longer travels out at boot. |
| Stepper driver / carrier | (TBD — e.g. A4988 / DRV8825 class) | GPIO logic-level Step/Dir/Enable | `EN` is active-LOW (`enable()` drives `EN_PIN` LOW). Micro-stepping set by `step_multiplier` = 32. Still enabled for homing. |
| Home limit / flag sensor | (TBD — optical or microswitch) | GPIO digital input (`HME_PIN`, active-HIGH) | Read by `isHome()`. **Still used after this change** — startup homing is retained. |
| Raspberry Pi GPIO header | RPi (BCM mode), 3.3 V logic | GPIO | Owns all four drawer signals listed below. |

### GPIO pin map — `Drawer` class, `sentri_lib/motor_class.py`

| Signal | Constant | BCM pin | Direction | Notes |
|--------|----------|---------|-----------|-------|
| Driver enable | `EN_PIN` | 12 | OUT (init HIGH = disabled) | Active-LOW enable |
| Step pulse | `STEP_PIN` | 5 | OUT | Pulsed `step_multiplier`× per logical step |
| Direction | `DIR_PIN` | 25 | OUT | `DIR_BACK_STATE`=LOW, `DIR_FORWARD_STATE`=HIGH |
| Home flag | `HME_PIN` | 24 | IN | Level returned by `isHome()` |

### Drawer motion parameters — `config_files/host_config.json` → `drawer`

| Parameter | Value | Meaning | Affected by this change? |
|-----------|-------|---------|--------------------------|
| `open_steps` | 4500 | Outward travel to loading position | **Yes** — this move no longer runs at startup |
| `close_steps` | 0 | Close target | No |
| `read_steps` | 152 | Travel to optics read position | No |
| `home_steps` | 5000 | Max steps to seek home flag | No — homing still runs at startup |
| `step_multiplier` | 32 | Micro-step pulses per logical step | No |

### Net hardware impact at startup

- **Before:** `drawer.home()` → `drawer.open()` (homes again, then drives out 4500 steps). Drawer ends **open**.
- **After:** `drawer.home()` only. Drawer ends at **home / closed**.
- The **home sensor and stepper driver are still exercised** (homing is retained); only the
  4500-step outward travel is eliminated at boot. **No component is removed, added, or rewired** —
  this is a control-logic change, not a hardware change.

---

## 3. Operating Parameters

- None

## 4. Control Logic

- None

---

## 5. Communication Protocol

- None
---

## 6. Calibration

- None

---

## 7. Failure Modes

- None

---

## 8. Known Limitations

- None

---

## 9. Testing in Simulation Mode

Which behaviors can be tested without hardware?

- None, behavior must be tested on a physical machine.

---

## 10. Related

- None
