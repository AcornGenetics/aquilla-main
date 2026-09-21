# ADR-022: The Profile Sync Agent runs as a native Greengrass component on the host, not inside the app container

**Status:** Accepted
**Date:** 2026-09-21
**Author:** Nicole Cornell
**Deciders:** Nicole Cornell
**Related:** acorn-fleet ADR-0002 (per-device profiles via Device Shadow + S3); aquilla-main #465 (the sync agent), #483/#484/#487 (the in-container implementation this supersedes)

---

## Context

acorn-fleet ADR-0002 delivers per-device profiles as a **Profile Assignment** in a
`profiles` Device Shadow plus **bodies in S3**, reconciled on-device by a **Profile
Sync Agent** into `/opt/aquila/profiles/managed/`. ADR-0002 specified the agent as
"its own small Greengrass component," but #465 implemented it **inside the backend
Docker container** (a FastAPI startup hook), fetching S3 with `boto3` and the
Token Exchange Role (TES) credentials from `AWS_CONTAINER_CREDENTIALS_FULL_URI`.

That does not work, and the failure is structural, not incidental:

- Greengrass's TES credential provider binds to **`127.0.0.1:35289` on the host**.
- The backend runs on the Docker **bridge network**, where `localhost` is the
  container's own loopback. It cannot reach the host's loopback-bound TES port —
  not via `localhost`, and not via `host.docker.internal` (the TES port is bound to
  `127.0.0.1`, not the bridge interface).
- So `boto3` inside the container cannot obtain credentials → the S3 fetch fails →
  no profile ever lands. Observed on sn01: `Could not connect to the endpoint URL:
  "http://localhost:35289/.../credentialprovider/"`.

The reconcile *logic* itself (add / overwrite-on-version-change / delete-on-removal;
`None`-means-keep-cache offline safety) is correct and tested — it is only the
**credential reach from within the container** that is broken.

Live options considered:

1. **Native Greengrass component on the host** (this ADR). The agent runs directly
   under the nucleus, where `127.0.0.1:35289` is reachable and the standard TES
   credential provider works. It writes to `/opt/aquila/profiles/managed/`, a host
   path already bind-mounted into the container; the app only *reads* it.
2. **aquila mTLS pull path.** The device fetches profiles over its existing mTLS
   identity (`device.crt`, already in the container) from a *new* cloud endpoint —
   no TES. Rejected: it requires building and securing new cloud infrastructure for
   the same outcome, when S3 + TES already exist and only need to be consumed from
   the right place. (This is the same alternative ADR-0002 rejected; its rejection
   premise — "S3 already exists" — holds, the container just wasn't the right caller.)
3. **Keep it in the container, force the creds through** (host networking, a
   host-side port-proxy, cred-URI rewriting). Rejected: host networking breaks the
   multi-container DNS/port model; a proxy is fragile against the dynamic TES port;
   all add moving parts to work around running in the wrong place.

Doing nothing leaves per-device managed profiles permanently non-functional.

---

## Decision

**We will run the Profile Sync Agent as its own native (non-Dockerized) Greengrass
component on the host, and the app container will only read the profiles it lands.**

Concretely:

- A new Greengrass component (separate from `com.acorn.sentri`) runs on the host. Its
  artifact is a thin entrypoint that **reuses the existing tested reconcile core**
  (`aquila_web/profile_sync.py`: `parse_desired` / `reconcile` / `reported_state`).
- It reads the `profiles` shadow over **Greengrass IPC (the local ShadowManager
  copy)** — works offline, no cloud round-trip, no new IAM.
- It fetches bodies from S3 with **`boto3` + the TES role**, which works because it
  runs on the host. **Read-only**: managed-profile *fetch* only. No S3 write.
- Runtime deps (`boto3`, `awsiotsdk`) are bundled as wheels and installed into a
  **component-private venv** in the recipe's Install lifecycle — no system/host
  Python pollution, no PyPI at deploy (offline-first).
- It reconciles on **startup**, on a **shadow delta**, and on a **~5-minute interval**
  backstop (the interval is what catches in-place S3 edits, which produce no delta).
- The **app container stops fetching entirely**: `start_profile_sync_agent()` is
  removed from `main.py`, and the `#484` compose additions (`PROFILES_BUCKET` + TES
  cred passthroughs) and `#487` (`boto3` in `requirements-backend.txt`) are reverted.
  `profile_sync.py` stays, now consumed by the component as a library.

**Scope:** managed-profile fetch (read) only. Local-profile run-provenance is out of
scope here and is *not* an S3 write (see the ADR-0002 §6 note below).

This is **hard to reverse** — it is a component-topology decision that other
device-side wiring (deploy pipeline, recipe, bind mounts) will build on.

---

## Consequences

### Positive
- The credential problem disappears: TES works natively on the host, no host
  networking / proxy / URI hacks.
- **Zero new cloud IAM** — TES already has S3 read; the shadow read uses the device's
  existing Greengrass identity over IPC.
- Profiles are decoupled from the app's lifecycle: an app crash/restart/redeploy no
  longer affects profile delivery, and vice versa.
- Restores the architecture ADR-0002 actually specified.

### Negative
- A genuinely new build/publish/deploy artifact (a second Greengrass component with
  its own recipe and release cadence).
- Reintroduces a *small, isolated* host-level Python footprint (a component-private
  venv) — the thing Docker was avoiding, though scoped and disposable, not system-wide.
- Rolls back the in-container plumbing shipped in #465/#484/#487 (the reconcile core
  is kept; the wiring is relocated).

### Follow-ups
- **acorn-fleet ADR-0002 §6 needs amending.** It states local-profile bodies are
  captured to versioned S3 by sha; in practice local profiles stay on the device and
  their provenance rides the `run_complete` event to acorn-internal-app. That drift
  should be reconciled in ADR-0002 (separate change).
- Build the component (recipe + entrypoint + bundled deps), publish it, and deploy it
  to the sandbox ring; verify on sn01 end-to-end (the aquilla-main #468 integration
  check).
