# ADR-006: JSON-Defined UI State Machine

**Status**: Accepted  
**Date**: 2026-04-30  
**Deciders**: Aquila Engineering Team

## Context

The Aquila UI moves through a well-defined set of screens: Ready → Running → Complete/Error. The hardware loop, API server, and kiosk frontend must all agree on the current screen state. This state needs to be inspectable and modifiable without a code deployment.

## Decision

Screen states are defined in `config_files/state_config.json` as a mapping of state IDs to human-readable screen names. The FastAPI backend exposes `/change_screen/{state_id}` to transition between states; the frontend WebSocket listener reacts to `screen_change` events and swaps the visible HTML section accordingly.

The hardware loop calls `state_requests.py` (an HTTP client wrapper) to trigger screen transitions at run milestones (run start, run complete, error).

## Consequences

**Positive**
- Screen names and IDs are decoupled from code; adding a new state requires only a `state_config.json` entry and a corresponding HTML section.
- State transitions are auditable via API logs without reading source code.
- The hardware loop, API, and UI share a common vocabulary defined in one file.

**Negative**
- State transitions are not validated for completeness; an invalid state ID will be accepted by the API but ignored by the UI.
- No guard conditions or transition rules are enforced (e.g., "can only go to Running from Ready"); invalid transitions are silently tolerated.
- `state_config.json` is fleet-wide; device-specific screen customization is not currently supported.

## Alternatives Considered

- **Enum in code**: type-safe but requires a deployment to add states; doesn't serve as shared vocabulary for API consumers.
- **State machine library** (e.g., `transitions`): adds guard/callback infrastructure but is heavier than the current simple screen-switch model.
- **Database-backed state**: enables remote state inspection but adds infrastructure complexity.
