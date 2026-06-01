# ADR-004: FastAPI + WebSocket for Real-Time State Synchronization

**Status**: Accepted  
**Date**: 2026-04-30  
**Deciders**: Aquila Engineering Team

## Context

During a PCR run, the UI must display live data: current cycle number, temperature setpoint vs. measured, optical readings, and run state (running/complete/error). This requires sub-second push updates from the hardware layer to the browser.

## Decision

The backend is implemented in **FastAPI** (Python) with **uvicorn** on port 8090. A single WebSocket endpoint (`/ws`) maintains a persistent connection with the UI. The hardware loop (running in a subprocess/thread) posts state updates to the FastAPI process via HTTP (`/change_state/`, `/change_screen/`); FastAPI broadcasts these to all connected WebSocket clients.

REST endpoints handle discrete operations: profile management (`/profiles/`), run control (`/run/`, `/stop/`), and results retrieval (`/history/`).

## Consequences

**Positive**
- WebSocket push eliminates polling; UI updates are near-instantaneous.
- FastAPI's async nature handles concurrent WebSocket connections and REST requests without blocking.
- Pydantic models provide runtime validation for all API request/response payloads.
- FastAPI's automatic OpenAPI docs (`/docs`) aid development and testing.

**Negative**
- WebSocket reconnect logic must be handled in the client (`script.js`); connection drops during a run must not lose state.
- The hardware loop communicates with the FastAPI server via localhost HTTP, introducing a round-trip; a direct shared-memory approach would be faster but harder to decouple.
- State is held in FastAPI process memory (not persisted); a server restart during a run would lose live telemetry (run data is persisted to `/opt/aquila/logs` independently).

## Alternatives Considered

- **Polling (AJAX)**: simpler but introduces latency and unnecessary server load.
- **Server-Sent Events**: one-way push; doesn't support bidirectional control signals.
- **MQTT**: appropriate for multi-device messaging but overkill for single-device local communication.
- **Flask + SocketIO**: viable but slower async model; FastAPI's native async is a better fit.
