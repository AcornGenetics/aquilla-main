# ADR-001: Hostname-Keyed Device Configuration

**Status**: Accepted  
**Date**: 2026-04-30  
**Deciders**: Aquila Engineering Team

## Context

The Aquila fleet consists of multiple physical devices (sn01, sn02, sn03…) that share the same software image but differ in hardware specifics: motor step counts, GPIO pin assignments, ADC channel mappings, and drawer offsets. A mechanism is needed to allow a single Docker image to run correctly on any device.

## Decision

All hardware-specific parameters are stored in `config_files/host_config.json`, structured as a dictionary keyed by device hostname (e.g., `"sn01"`, `"sn02"`). At runtime, `aq_lib/config_module.py` reads `DEVICE_HOSTNAME` from the environment and selects the matching config block.

If a flat (non-keyed) JSON layout is detected, the loader falls back to treating the entire file as a single device's config, supporting standalone development setups.

## Consequences

**Positive**
- One container image serves the entire fleet; hardware differences are externalized.
- Adding a new device variant requires only a new entry in `host_config.json`, not code changes.
- Device-specific bugs are isolated to config entries, not shared code.

**Negative**
- `host_config.json` grows as the fleet scales; becomes a single point of failure for hardware config.
- Requires `DEVICE_HOSTNAME` to be set correctly in `device.env` at provisioning time.
- No schema validation on the JSON; a malformed entry causes a runtime failure on that device.

## Alternatives Considered

- **Per-device config files**: simpler per file, but requires managing N files and selecting the correct one at deploy time.
- **Database-backed config**: supports dynamic updates but adds infrastructure complexity inappropriate for embedded devices.
- **Environment variables per parameter**: too many variables; impractical for dozens of hardware parameters.
