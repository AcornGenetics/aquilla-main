# Hardware Spec: [Subsystem Name]

**Status:** Draft | Review | Active | Deprecated
**Author:** [Name]
**Last updated:** YYYY-MM-DD
**Subsystem:** Thermal | Motor | LED | ADC | Lid | Comms | Other
**Source file(s):** `aq_lib/[filename].py`

---

## 1. Overview

What does this subsystem do? What physical hardware does it control or read?

---

## 2. Hardware Components

| Component | Part / Model | Interface | Notes |
|-----------|-------------|-----------|-------|
| [e.g., Peltier TEC] | [part number] | UART / I2C / GPIO | [any quirks] |
| [e.g., Thermistor] | [part number] | ADC | [calibration needed?] |

---

## 3. Operating Parameters

| Parameter | Min | Nominal | Max | Unit |
|-----------|-----|---------|-----|------|
| [e.g., Block temp] | 4 | 60 | 95 | °C |
| [e.g., Ramp rate] | — | 2 | 5 | °C/s |
| [e.g., Motor speed] | 0 | — | 100 | % duty |

**Safety limits:** [Any hard limits that must never be exceeded]

---

## 4. Control Logic

Describe the control loop or sequence:

```
Init → [step] → [step] → [steady state] → [shutdown]
```

- What triggers start/stop?
- What happens on failure or timeout?
- How does simulation mode differ? (`AQ_DEV_SIMULATE=1` env flag)

---

## 5. Communication Protocol

For serial/I2C/SPI subsystems:

- **Protocol:** [UART / I2C / SPI / GPIO]
- **Baud rate / address:** [value]
- **Key commands / registers:** [list or table]
- **Error handling:** [how errors are detected and surfaced]

Reference: `aq_lib/[module].py`, class `[ClassName]`, method `[method_name]`

---

## 6. Calibration

- Is factory calibration required? [Yes/No]
- Is field calibration possible? [Yes/No]
- Calibration procedure: [steps or "see docs/debugging/calibration.md"]
- Where calibration values are stored: [config file path]

---

## 7. Failure Modes

| Failure | Symptom | Cause | Recovery |
|---------|---------|-------|----------|
| [e.g., Thermal runaway] | Temp > 95°C | TEC fault | Shutdown, alert |
| [e.g., No ADC signal] | ADC returns 0 | Cable disconnect | Error state, log |

---

## 8. Known Limitations

- [Hardware quirks, edge cases, or things that differ between device generations]
- [Any behavior that is intentionally not handled]

---

## 9. Testing in Simulation Mode

Which behaviors can be tested without hardware?

- `AQ_DEV_SIMULATE=1` stubs: [list what is stubbed]
- What cannot be simulated: [list]
- Test file: `tests/[path]`

---

## 10. Related

- ADR: `docs/adr/ADR-XXX-[name].md` (if an architectural decision was made)
- Debugging guide: `docs/debugging/[subsystem].md`
- Source: `aq_lib/[filename].py`
