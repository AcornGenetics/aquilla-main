# ADR-005: Kiosk Runs on Host X11 (Not Inside Container)

**Status**: Accepted  
**Date**: 2026-04-30  
**Deciders**: Aquila Engineering Team

## Context

The Aquila device uses a touchscreen display directly attached to the Raspberry Pi. The UI must render full-screen in kiosk mode with touch support, screen rotation, and on-screen keyboard. Containerizing the display layer introduces significant X11/Wayland forwarding complexity on embedded hardware.

## Decision

Chromium runs directly on the **host OS X11 session** (not inside a Docker container), managed by a **systemd service** (`aquila-kiosk.service`). It connects to the FastAPI backend running in Docker via `http://localhost:8090`.

Screen rotation is handled by `update_kiosk_x11.sh` (xrandr). Touch input is enabled via Chromium flags: `--touch-events=enabled --enable-touch-drag-drop --disable-pinch`. The kiosk service starts automatically at boot after the X session is available.

## Consequences

**Positive**
- Direct access to X11/input devices; no passthrough or forwarding needed.
- xrandr, GPU acceleration, and touch calibration work natively.
- Chromium on host benefits from full OS-level GPU driver support.
- Kiosk can be restarted independently of the backend containers.

**Negative**
- The kiosk is not containerized; OS-level Chromium updates are not managed by Docker/Watchtower.
- A host OS update could break Chromium behavior without triggering a container rebuild.
- The `DISPLAY` environment variable must be set correctly in the systemd service unit.
- Cross-container display forwarding (e.g., `--device /dev/dri`) would be needed to containerize this layer in the future.

## Alternatives Considered

- **Chromium in container with X11 socket forwarding**: adds `/tmp/.X11-unix` volume mount complexity; GPU passthrough unreliable on Pi.
- **Electron app**: heavier runtime; adds another packaging and update mechanism.
- **WebKit2GTK kiosk** (e.g., `cage` + `wpewebkit`): investigated but CSS `touch-action` support was incomplete (see `kiosk-touch-fix.md`).
