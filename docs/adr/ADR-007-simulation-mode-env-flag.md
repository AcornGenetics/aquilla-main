# ADR-007: Simulation Mode via Environment Flag

**Status**: Accepted  
**Date**: 2026-04-30  
**Deciders**: Aquila Engineering Team

## Context

The Aquila hardware (TEC controller, ADC, GPIO steppers) is unavailable in CI environments and developer workstations. Tests and UI development must be possible without physical hardware. A mechanism is needed to run the full application stack in a "fake" mode that exercises all code paths except hardware I/O.

## Decision

An environment variable `AQ_DEV_SIMULATE=1` switches the application into simulation mode. In this mode:

- The thermal profile execution is faked (time-compressed); no Meerstetter RS-232 commands are sent.
- ADC reads return synthetic fluorescence curves instead of real hardware samples.
- Motor and drawer commands are no-ops; GPIO is not initialized.
- The FastAPI backend and WebSocket state sync operate identically to production.

Simulation mode is activated in `compose.yaml` for local development and in the GitHub Actions CI environment.

## Consequences

**Positive**
- CI and local development work without hardware; all API, state-machine, and UI tests run in simulation.
- Full integration tests can validate the run pipeline end-to-end without a PCR device.
- Developers can iterate on UI and analysis code without physical access to a device.

**Negative**
- Simulation behavior must be kept in sync with real hardware behavior; drift between them can mask integration bugs.
- Synthetic ADC data may not cover all edge cases (noisy signal, crosstalk saturation) that real hardware produces.
- Simulation mode is controlled by a single env var with no sub-mode granularity (e.g., "simulate ADC only, use real motors").

## Alternatives Considered

- **Mock objects in test code only**: keeps production code clean but doesn't allow running the full application stack in CI.
- **Hardware-in-the-loop CI**: most accurate but requires dedicated lab infrastructure attached to the CI runner.
- **Separate `simulate.py` entry point**: cleaner separation but duplicates application startup logic.
