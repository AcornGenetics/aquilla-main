# ADR-002: Docker + Watchtower for Fleet OTA Updates

**Status**: Accepted  
**Date**: 2026-04-30  
**Deciders**: Aquila Engineering Team

## Context

Fleet devices run in the field with limited operator intervention. Software updates must be delivered reliably without requiring manual SSH access to each device, while preserving run history and device-specific configuration across updates.

## Decision

All application services (API, app loop) are containerized via Docker Compose. **Watchtower** runs as a sidecar container and polls GHCR on a configurable schedule; when a new image tag is detected, it pulls and restarts the relevant services automatically.

Persistent state (PCR results, profiles, logs) is stored in `/opt/aquila` on the host filesystem, mounted as a Docker volume. This directory survives container replacement.

Device-specific files (`device.env`, `host_config.json`, profiles) are placed under `/opt/fleet` at provisioning time and bind-mounted into containers at startup.

## Consequences

**Positive**
- Zero-touch OTA updates: push a new image tag to GHCR and all fleet devices self-update.
- `/opt/aquila` persistence decouples data lifecycle from container lifecycle.
- Rollback is possible by pinning a previous image tag in `device.env`.

**Negative**
- Watchtower restart causes a brief service interruption; must not update mid-run (not currently enforced).
- GHCR credentials must be stored securely on device (`~/.docker/config.json`); leaked credentials allow unauthorized image pushes.
- No staged/canary rollout at the container level without additional tooling (see `docs/deployment/ring_rollout.md`).

## Alternatives Considered

- **Ansible/Salt push**: requires network access from a control plane to each device; adds infrastructure.
- **apt-based packages**: tighter OS integration but slower release cycle and harder dependency isolation.
- **Manual `docker pull`**: simple but requires operator action per device.
