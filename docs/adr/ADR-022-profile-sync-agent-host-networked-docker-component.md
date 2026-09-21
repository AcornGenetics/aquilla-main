# ADR-022: The Profile Sync Agent runs as its own host-networked Docker Greengrass component, separate from the app

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

The key asymmetry: a program that reaches `127.0.0.1:35289` gets TES creds; one on
the bridge network does not. So the agent must run somewhere with the host's
network view — but *separate from the app* (the app container must stay on the
bridge for its inter-container DNS, `aquila-backend`↔`aquila-app`).

Live options considered:

1. **Its own host-networked Docker component** (this ADR). A dedicated, single-
   purpose container (`com.acorn.profile-sync`) with `network_mode: host`, so
   `localhost:35289` is the host's TES port and boto3's standard credential
   provider works. `boto3` is baked into a slim image (no runtime install). It
   mounts the nucleus IPC socket (shadow) and `/opt/aquila/profiles` (writes
   `managed/`, which the app only reads). Reuses the existing image → ECR → recipe
   → publish-component pipeline. Host networking is safe here because this container
   is single-purpose, binds no ports, and needs no inter-container DNS — the reason
   the *app* stack can't go host-net does not apply.
2. **Native (non-Docker) host component with a component-private venv.** Also reaches
   TES (host process). Rejected: it revives the host-`venv` + systemd pattern the
   fleet deliberately migrated *off* (old `deployment1.sh`), and drags back
   cross-architecture wheel matching (`aarch64` + the Pi's exact Python, the
   `awscrt` native ext), a `python3-venv` host dependency, and a venv built on-device
   at deploy — the same "silently doesn't work on the device" failure class this
   whole effort has been fighting. More fragile, off-grain, and needs a new build path.
3. **aquila mTLS pull path.** The device fetches profiles over its existing mTLS
   identity (`device.crt`) from a *new* cloud endpoint — no TES. Rejected: it
   requires building and securing new cloud infrastructure for the same outcome,
   when S3 + TES already exist and only need to be consumed from the right place.
   (Same alternative ADR-0002 rejected; its premise — "S3 already exists" — holds,
   the bridge-net container just wasn't the right caller.)
4. **Keep it in the app container, force the creds through** (host-net the whole app
   stack, a host-side port-proxy, cred-URI rewriting). Rejected: host-netting the
   app stack breaks its multi-container DNS/port model; a proxy is fragile against
   the dynamic TES port; all work around running in the wrong place.

Doing nothing leaves per-device managed profiles permanently non-functional.

---

## Decision

**We will run the Profile Sync Agent as its own single-purpose, host-networked Docker
Greengrass component (`com.acorn.profile-sync`), separate from the app container,
which only reads the profiles the agent lands.**

Concretely:

- A new Greengrass **Docker** component (separate image from `com.acorn.sentri`) runs
  a thin entrypoint (`aquila_web/profile_sync_main`) that **reuses the tested core**
  (`profile_sync.py` reconcile + `ProfileSyncAgent` + `SyncCoordinator`). `boto3` and
  `awsiotsdk` are **baked into a slim image** — no on-device install, no cross-arch
  wheels, no host `venv`/`python3-venv`.
- The component runs with **`network_mode: host`**, so `localhost:35289` is the host's
  TES port and boto3's credential provider works. It mounts the nucleus IPC socket
  (shadow reads) and `/opt/aquila/profiles` (writes `managed/`; the app only reads it).
- It reads the `profiles` shadow over **Greengrass IPC (local ShadowManager copy)** —
  offline-friendly, no new IAM. It fetches bodies from S3 with **`boto3` + the TES
  role**. **Read-only**: managed-profile *fetch* only, no S3 write.
- It reconciles on **startup**, on a **shadow delta**, and on a **~5-minute interval**
  backstop (the interval catches in-place S3 edits, which produce no delta).
- Built + published through the **existing image → ECR → recipe → publish-component
  pipeline** (a slim `Dockerfile.profile-sync` + a `profile-sync-compose.yaml` +
  recipe generation), never hand-published.
- The **app container stops fetching entirely**: `start_profile_sync_agent()` removed
  from `main.py`; the `#484` compose additions (`PROFILES_BUCKET` + TES passthroughs)
  and `#487` (`boto3` in `requirements-backend.txt`) reverted. `profile_sync.py`
  stays, now consumed by the component as a library.

**Scope:** managed-profile fetch (read) only. Local-profile run-provenance is out of
scope here and is *not* an S3 write (see the ADR-0002 §6 note below).

This is **hard to reverse** — it is a component-topology decision that other
device-side wiring (deploy pipeline, recipe, bind mounts) will build on.

---

## Consequences

### Positive
- The credential problem disappears: host networking puts TES on `localhost` where
  boto3 expects it — no proxy, no URI rewriting, no cross-arch wheels.
- **Reuses the existing image → ECR → recipe → publish pipeline** — no new build path,
  and `boto3` baked in an image is deterministic (works in CI ⇒ works on the Pi),
  avoiding the "silently missing/mismatched on-device" failures.
- **No host dependencies** — no `python3-venv`, no on-device venv build; stays on the
  repo's "everything is a container" grain.
- **Zero new cloud IAM** — TES already has S3 read; the shadow read uses the device's
  existing Greengrass identity over IPC.
- Profiles decoupled from the app's lifecycle: an app crash/restart/redeploy no longer
  affects profile delivery, and vice versa. Satisfies ADR-0002's "own component" intent.

### Negative
- A genuinely new build/publish/deploy artifact (a second component + slim image with
  its own release cadence).
- The component runs on the **host network namespace** — reduced network isolation for
  that one container. Scoped and acceptable: it's single-purpose, first-party,
  read-only, binds no ports, and makes only outbound calls (IPC socket + S3).
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
