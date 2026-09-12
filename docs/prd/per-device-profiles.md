# PRD: Per-device Profiles via Device Shadow + S3 (decouple Profiles from releases)

**Status:** Ready for agent
**Author:** Nicole Cornell
**Date:** 2026-09-09
**Issue:** AcornGenetics/aquilla-main#455
**Related:** acorn-fleet ADR-0002 (per-device profiles via Device Shadow + S3), acorn-fleet ADR-0001 (fleet management via AWS IoT Greengrass), aquilla-main ADR-001 (hostname-keyed device config — superseded for profiles)
**Glossary:** CONTEXT.md — **Managed Profile**, **Local Profile**; acorn-fleet CONTEXT.md — **Profiles Shadow**, **Profile Assignment**, **Ring**, **Component**, **Deployment**, **Run**

## Problem Statement

Today, when we want a specific Sentri to have a specific set of assay Profiles, we have to change files that are baked into the container image (`profiles/bundled/` plus the hostname-keyed maps `device_profiles.json` / `profile_groups.json`) and then ship a whole new release — publishing a new `com.acorn.sentri` Component version and deploying it through every Ring. Getting one device the profiles it needs means pushing an update to the entire fleet.

This is painful in three ways:

- **Profiles are welded to the release.** Changing which Profiles a device has, or the contents of a Profile, both require an image rebuild + Greengrass deployment. There is no way to change one device without a fleet-wide release.
- **The per-device config is set but not remotely reachable.** It can only change through a rebuild, and every device ships every other device's config. The drift is already visible: `profile_groups.json` contains hand-faked per-device groups (`"sn04 brewery"`, `"sn10 brewery"`, …) and per-device Profile files (`ABBA_sn005.json`, `verification_profile_sn10.json`).
- **No run-level provenance.** A completed Run records only the Profile *name*, not the exact recipe contents that produced the result.

We want to put specific Profiles on a specific device, and change them (assignment and contents) remotely, **without** a release and **without** version drift — the Component version must stay identical across a Ring, with Profiles the only per-device difference, while Profiles remain reachable for the team to change when needed.

## Solution

Move Profiles off the container image and make each device's Profile set a per-Thing attachment delivered through `acorn-fleet`, per ADR-0002 (`acorn-fleet/docs/adr/0002-per-device-profiles-via-device-shadow.md`).

- **Managed Profile** bodies live as objects in the existing S3 `ArtifactsBucket` (versioning enabled).
- Each Sentri gets a named **Profiles Shadow** (`.../shadow/name/profiles`) whose `desired` state is a flat list of S3 keys — that device's **Profile Assignment**.
- A new on-device **sync agent** (its own small Greengrass Component) reconciles the local `managed/` Profile directory against the Shadow + S3, and reports back what it actually has.
- Assigning a Profile to a device is one `UpdateThingShadow` call and affects only that device. The `com.acorn.sentri` Component version stays identical across a Ring.
- **Managed Profiles** are always read-only on the device; **Local Profiles** (authored on-device in the builder) remain editable. The per-device edit-lock flag is removed.
- Every Run stamps `{Profile name, canonical content sha256}` into the `run_complete` event, so the exact recipe is reconstructable from versioned S3 — provenance survives even though Profiles are now mutable.

From the team's perspective: upload a Profile JSON to S3 once, then add its key to a device's Shadow. It appears on that device, and only that device, with no release. Editing a Profile is a re-upload; the device picks it up on its own.

## User Stories

1. As an Acorn engineer, I want to assign a specific Profile to one Sentri with a single Shadow edit, so that I don't have to ship a release to the whole fleet to change one device.
2. As an Acorn engineer, I want to change the *contents* of a Profile remotely, so that fixing a recipe doesn't require an image rebuild.
3. As an Acorn engineer, I want the `com.acorn.sentri` Component version to stay identical across a Ring, so that Profiles are the only thing that differs between devices and I never introduce version drift.
4. As an Acorn engineer, I want to attach a Profile to several named devices by editing each of their Shadows, so that I can roll a new assay to exactly the devices that should have it.
5. As an Acorn engineer, I want to detach a Profile from a device by removing its key from the Shadow, so that a device stops offering a Profile it should no longer run.
6. As an Acorn engineer, I want to upload a Profile body to S3 once and point many devices' Shadows at the same key, so that shared Profiles aren't duplicated per device.
7. As an Acorn engineer, I want to assign Profiles with plain AWS CLI/console for now, so that we can ship this without first building a UI.
8. As an Acorn engineer, I want to omit the sha256 in the Shadow and still have edits picked up, so that I don't have to compute and paste hashes by hand.
9. As an Acorn engineer, I want the device to report back (in the Shadow's `reported`) which Profiles it actually has, so that I can confirm an assignment landed and spot drift via Fleet Indexing.
10. As an on-device operator, I want Managed Profiles assigned to my Sentri to appear in the Profile picker, so that I can select and run them.
11. As an on-device operator, I want Managed Profiles to be read-only, so that I can't accidentally alter a controlled assay recipe.
12. As an on-device operator, I want to keep authoring and editing my own Local Profiles, so that on-device experimentation is unaffected by the new managed-delivery path.
13. As an on-device operator, I want a Run I've already started to keep running unaffected if a Profile syncs mid-run, so that a remote change never interrupts an assay in progress.
14. As an on-device operator, I want the device to keep running its last-known Profiles when it's offline, so that loss of connectivity never stops me from running assays.
15. As an on-device operator, I want a device that has never synced (fresh or factory-reset, offline) to clearly show "No profiles available," so that I'm not misled into thinking it's broken versus simply unprovisioned.
16. As an on-device operator, I want a newly assigned Profile to appear without any manual "apply" step, so that using it is frictionless.
17. As an on-device operator, I want to select a Managed Profile and start a Run that executes its exact thermal steps, so that the new delivery path runs assays identically to before.
18. As a quality/analytics user, I want each Run to record the exact Profile contents (by canonical hash) that produced it, so that I can prove which recipe generated a given result even after the Profile is later changed.
19. As a quality/analytics user, I want the exact recipe reconstructable from S3 by the recorded hash, so that provenance lookups don't require the Profile body to be stored on the device or in every Run record.
20. As a quality/analytics user, I want Runs that used a Local Profile to also be reconstructable, so that provenance has no gap for on-device-authored Profiles.
21. As an Acorn engineer, I want an edit made in place (same S3 key, new contents) to be detected and re-pulled by the device, so that I can fix a Profile without renaming files.
22. As an Acorn engineer, I want the sync to be resumable and idempotent, so that a partial or interrupted sync converges to the assigned set on the next run without manual cleanup.
23. As an Acorn engineer, I want Local Profiles to be untouched by the sync agent, so that reconciling Managed Profiles never deletes or overwrites an operator's own work.
24. As an Acorn engineer, I want to promote a Component release to a Ring without it resetting or requiring any change to Profile Assignments, so that release cadence and Profile management are fully independent.
25. As a platform maintainer, I want the baked profile path (image COPY, entrypoint copy, hostname filter) removed once the new path is proven, so that there's a single source of truth for a device's Profiles.

## Implementation Decisions

**Delivery model (per ADR-0002).**
- Managed Profile bodies are stored as objects in the S3 `ArtifactsBucket`; the device's Token Exchange Role already grants read.
- Per-device assignment lives in a named Device Shadow `profiles` whose `desired.profiles` is a **flat list of `{ key }`** entries (sha256 optional). No group indirection.
- A new device-side **sync agent** runs as its own small Greengrass Component. It reads `desired` (over Greengrass IPC / ShadowManager local cache), reconciles the local Managed directory against S3, and writes the applied set into `reported`.

**On-device directory model.**
- `profiles/bundled/` is renamed conceptually to **`managed/`**; the sync agent owns this directory. `profiles/local/` is unchanged and never touched by the agent.
- The Profile listing endpoint continues to list whatever is in `managed/` + `local/`. The baked hostname filter (`resolve_device_profiles`) and the two config files (`device_profiles.json`, `profile_groups.json`) are removed.

**Profile classes.**
- **Managed Profiles**: team-pushed, S3-backed, delivered via the Shadow, **always read-only** on every device. Because they can't be edited on-device, their on-device bytes always equal S3.
- **Local Profiles**: authored on-device, always editable, never in S3.
- The per-device `profile_editing_disabled` flag is dropped; the lock is now a property of the class, not the device.

**Reconcile behavior (functional core).**
- Reconcile is a pure decision over `(desired keys, current managed-dir state, a fetch capability)` producing writes / deletes / reported state. IO (Shadow read, S3 fetch, file writes, S3 uploads) is injected, so behavior is testable without network or IPC.
- Keys present in `desired` but missing/changed locally are fetched from S3; keys no longer in `desired` are deleted from `managed/`; `local/` is never considered.
- **Edit detection**: in-place edits (same key, new contents) are detected via S3 object versioning (the object's version marker), not a hand-maintained hash. sha256 in the Shadow is advisory: if present and mismatched, the agent surfaces the mismatch in `reported` rather than silently dropping the Profile.
- **Idempotent/resumable**: rerunning reconcile converges to the assigned set.

**Offline / bootstrap.**
- Managed bodies are cached persistently in the `/opt/aquila/profiles` volume; offline = keep running the last-synced set.
- A device with an empty Managed cache that has never synced presents "No profiles available" (fail-closed). No baked fallback Profile set.

**Run provenance.**
- At Run start, compute a **canonical whole-document** hash of the loaded Profile: stable JSON serialization (sorted keys, fixed separators) then SHA-256, stored tagged as `canon-v1:sha256:…`. Computed once at load so it reflects the exact bytes that ran.
- Thread `{ profile_name, profile_sha256 }` into the `run_complete` event; it flows through the existing local outbox → Sync → `acorn-analytics` pipeline. The event contract gains an optional `profile_sha256` field (legacy fallback when absent, mirroring how `run_timestamp` was added).
- For Managed Profiles, `{name, sha}` + versioned S3 is sufficient to reconstruct the recipe. For **Local Profiles**, the device captures the Profile body up to the versioned S3 bucket by sha as part of the Run sync, so reconstruction is uniform across both classes.
- Reconstruction of the exact recipe from S3 by sha is a read performed by `acorn-internal-app`/analytics consumers; the device stores only the reference.

**acorn-fleet CDK deltas (dependency; see ADR-0002).**
- Extend ShadowManager sync configuration to include `namedShadows: ['profiles']`.
- Add `'profiles'` to `INDEXED_NAMED_SHADOWS` so assignments are queryable in Fleet Indexing.
- Enable **versioning** on the `ArtifactsBucket`; ensure lifecycle rules do not expunge versions still referenced by Run records.
- Per-Thing Shadow read/write is already covered by the existing device IoT policy and Token Exchange Role — no new policy expected.

**Deferred.**
- An `acorn-internal-app` "assign Profiles to device" UI (upload + assignment + who-has-what view) is a follow-up; v1 authoring is raw AWS CLI/console.

## Testing Decisions

Good tests here assert **external behavior at the highest honest seam** — what a device offers and runs, what the listing endpoint returns, what the `run_complete` event carries, and what the CDK template declares — never internal call sequences or IPC plumbing. IO is injected so tests need no network, no AWS, and no hardware.

**Modules and seams to test (aquilla-main unless noted):**

1. **Sync-agent reconcile (new unit seam, functional core).** Test `reconcile(desired_keys, current_managed_state, fetch) → {writes, deletes, reported}` with an injected fake fetcher and a temp directory. Cases: add a new key; detect an in-place edit (changed version) and re-pull; delete a key removed from `desired`; never touch `local/`; empty `desired` → empty managed set; unreadable Shadow → keep current cache (offline); advisory sha mismatch surfaces in `reported`; idempotent rerun. Prior art: the unit-test style in `unit_tests/` (e.g. `test_device_profile_filtering.py`, `test_enroll.py`).

2. **Profile listing (existing contract seam).** `GET /profiles` lists `managed/` + `local/`, with Managed Profiles marked read-only. Prior art: `tests/contract/test_bundled_profiles.py`. The old per-device filtering / edit-lock tests (`tests/contract/test_profile_device_filtering.py`, `unit_tests/test_device_profile_filtering.py`, `unit_tests/test_profile_editing_lock.py`) are **retired or rewritten** — the baked hostname filter and per-device flag no longer exist; the new invariant is "Managed = always locked, no per-device filtering."

3. **Run provenance (new unit seam + existing contract seam).** Unit-test the pure `canonical_profile_hash(json) → "canon-v1:sha256:…"` — same contents in any key order/formatting yield the same hash; any real content change changes it. Contract-test that `run_complete` carries `profile_sha256` for the selected Profile, with legacy fallback when absent. Prior art: `unit_tests/test_estimated_completion.py` / `test_profile_assembly.py` (pure logic), `tests/contract/test_history_endpoints.py` (run/event contract). Local-Profile capture-to-S3-by-sha is asserted at the emit seam with an injected uploader.

4. **CDK template (existing seam, acorn-fleet).** Fine-grained template assertions: ShadowManager config includes `namedShadows: ['profiles']`; `INDEXED_NAMED_SHADOWS` includes `'profiles'`; `ArtifactsBucket` has versioning enabled. Prior art: `acorn-fleet/tests/deploy-stack.test.ts`, `registry-stack.test.ts`, `device-access-stack.test.ts`.

5. **Managed Profile still runs (existing run seam, simulation mode) — the key regression guard.** Drive the real Run flow in `RUN_MODE` simulation against a Profile placed in `managed/` exactly as the sync agent would produce it (fixture reuses seam 1 output): the Profile appears in `GET /profiles`; it is selectable via `POST /profile/select`; editing it is rejected (Managed = locked); the Run loads that Profile's steps and executes to completion; and `run_complete` fires with `{name, canonical sha256}` matching that exact Profile. Prior art: `tests/contract/test_dev_update_simulation.py` and the `_simulate_run` path. This proves the new delivery path is listable → selectable → **runnable** → provenance-stamped, end to end.

## Out of Scope

- The `acorn-internal-app` UI for assigning Profiles / uploading bodies / viewing who-has-what (deferred; v1 is CLI/console).
- Group / profile-group abstractions — v1 is a flat per-device key list. Groups can be added later without changing the device agent (it always receives a resolved list).
- Content-addressed S3 keys (sha as filename) — rejected in favor of mutable keys + S3 versioning so operators need not compute hashes.
- Any change to how a Run executes a selected Profile's steps (the thermal engine is unchanged).
- Greengrass per-Thing *deployments* or `configurationUpdate.merge` for Profiles — rejected; Profiles are device state, not deployment state.
- Migrating historical Runs to backfill `profile_sha256` (new events only; legacy rows keep name-only).

## Further Notes

- This PRD depends on the `acorn-fleet` CDK deltas landing (ShadowManager named-shadow sync, Fleet Indexing, S3 versioning). See `acorn-fleet/docs/adr/0002-per-device-profiles-via-device-shadow.md`.
- Rollout is staged and reversible: build the sync agent, prove it on one device joined to the `sandbox` Ring alongside the still-baked Profiles, then cut over and remove the baked path (`docker/Dockerfile.api` `COPY profiles/bundled/`, the `cp -f` loop in `docker/entrypoint.sh`, and `device_profiles.json` / `profile_groups.json` + `resolve_device_profiles`).
- Provenance is only as durable as S3 retention: versioning must stay enabled and lifecycle rules must not delete versions still referenced by Run records.
- Terminology: "bundled" is retired in favor of **Managed Profile**; glossary updated in `acorn-fleet/CONTEXT.md` and `aquilla-main/CONTEXT.md`.
