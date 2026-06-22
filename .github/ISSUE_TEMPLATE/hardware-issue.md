---
name: Hardware Issue
about: Problem with physical device behavior or hardware interface code
labels: hardware
assignees: ''
---

## Summary

One sentence describing the hardware issue.

## Hardware Affected

- [ ] Thermal (TEC / Meerstetter)
- [ ] Motor
- [ ] LED
- [ ] ADC
- [ ] Lid sensor
- [ ] Serial/comms
- [ ] Other: ___

## Device Info

- Device hostname / serial: [e.g., sentri-001.local]
- Is this reproducible on multiple devices? Yes | No | Unknown

## Symptom

What does the operator or engineer see? Include:
- Log lines from `logs/aquila.log`
- LED state
- Screen state
- Temperature / sensor readings if relevant

## Steps to Reproduce

1.
2.
3.

## Does It Reproduce in Simulation Mode?

Run `SIMULATION=true python application.py` and try to reproduce.
- [ ] Yes, also fails in simulation
- [ ] No, simulation is fine (hardware-specific)
- [ ] Not applicable

## Relevant Spec

`specs/hardware/[subsystem].md`

## Relevant ADR

`docs/adr/[ADR-XXX].md` (if this relates to an architectural decision)
