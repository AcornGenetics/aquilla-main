# ADR-016: aquila → sentri rebrand, and the fleet cutover sequence

**Status:** Accepted
**Date:** 2026-06-19
**Author:** Nicole Cornell
**Deciders:** Nicole Cornell

Tracks issue #178.

---

## Context

"Aquila" was the internal pre-launch codename for the PCR instrument; "Sentri"
is the product brand. The device already *is* a Sentri in our own glossary
(`CONTEXT.md`) — the code just hadn't caught up. Issue #178 makes the full
rename in scope: the GitHub repo (`AcornGenetics/aquilla-main` → `…/sentri`),
the application code and directories, CI/CD, and the deployment pipeline.

A naive "rename the repo and find-replace `aquila`" looks mechanical but is not,
because two facts about the production fleet turn parts of it into a stateful
migration:

1. **The fleet is Docker-based with Watchtower auto-updates.** Every device runs
   `fleet-config/docker-compose.yml` with a first-class `watchtower` container
   that auto-pulls `ghcr.io/${GHCR_REPO:-acorngenetics/aquilla-main}-{api,ui}:prod`
   by label. `GHCR_REPO` lives in each device's `/opt/fleet/.env` (written by
   `scripts/deploy/deployment2.sh`), and is the single control point for the
   image namespace, the `raw.githubusercontent.com` compose fetch, and the
   `api.github.com` token check in `fleet-update.sh`.

2. **GHCR package paths do not redirect on a repo rename.** A GitHub *repo*
   rename 301-redirects web, git, `api.github.com`, and `raw.githubusercontent.com`
   — but **not** GHCR packages. After the rename, CI publishes to
   `ghcr.io/acorngenetics/sentri-{api,ui}`, while the old `aquilla-main-*`
   packages **freeze at their last tag yet still resolve**.

The forcing function: if we just rename, every field device's Watchtower keeps
polling the now-frozen `aquilla-main-api:prod`, sees no newer digest, and the
device **silently sticks on the last pre-rebrand image forever** — no error, no
new releases. With no fleet-wide orchestrator (device access is manual via
Tailscale SSH), there is no automatic way to notice or correct this.

If we did nothing special: a "successful" rename would quietly strand the fleet.

### Footprint and scope decisions

The literal `aquila`/`aquilla` footprint is ~1,116 occurrences across 155 files
(#178). Two adjacent namespaces the string-grep misses were considered
separately:

- **`aq_` source packages** (`aq_lib`, `aq_curve`; 99 files, 182 imports) —
  **in scope.** No packaging metadata or entry points; they resolve from
  `PYTHONPATH`. Renaming to `sentri_lib` / `sentri_curve` is pure source, atomic
  on image pull, nothing persisted references them. Cost is only diff size.
- **`AQ_` environment variables** (`AQ_SYNC_DEVICE_ID`, `AQ_SYNC_ENDPOINT`,
  `AQ_SRC_BASEDIR`, …; ~16 vars, 35 files) — **out of scope, deliberately.**
  Their *values* are set in each device's environment; renaming the keys turns a
  string-replace into a per-device stateful migration, and `AQ_SYNC_DEVICE_ID`
  is the cert-bound device identity. Zero user-visible benefit, real breakage
  risk. The codename surviving in an env prefix is an accepted invisible seam.
- **`/opt/aquila` host state directory** — **out of scope, deliberately**, same
  rationale: it holds `device.env`, calibration, results, and logs on every
  device, and `AQ_SRC_BASEDIR` (a kept var) names it. To keep a future migration
  cheap, the bind-mount paths are parameterized behind a `STATE_DIR` var
  (default `/opt/aquila`), so a later flip is one env line + `mv` + `up -d`.
- **`container_name`s** (`aquila-app/-ui/-backend/-watchtower`) — **in scope.**
  Cosmetic, fully internal, atomic on the next `up -d`; the brand should show in
  `docker ps`.

`CONTEXT.md` records the glossary outcome: **Sentri** is the brand, **Aquila**
is the retired codename surviving only in the `AQ_` prefix and `/opt/aquila`.

---

## Decision

**Do the full code/CI rename, but cut the fleet over with a config-push-first,
dual-publish sequence — never let a device point at a path that stops receiving
updates while still resolving.**

### Repo / CI

1. Rename the GitHub repo to `AcornGenetics/sentri`. CI derives image names from
   `$GITHUB_REPOSITORY`, so published images become `…/sentri-{api,ui}`
   automatically. Edit the hardcoded `acorngenetics/aquilla-main` defaults in
   `docker/docker-compose.yml` and `fleet-config/docker-compose.yml` (they do
   **not** follow the rename).
2. For one release cycle (~1 week), CI **dual-publishes** to both
   `aquilla-main-*` and `sentri-*` as a backstop for any device not yet flipped.

### Fleet cutover (per device, manual over Tailscale SSH; ~8 devices)

3. **Canary first.** On one device, set `GHCR_REPO=acorngenetics/sentri` in
   `/opt/fleet/.env` and run `fleet-update.sh`. Confirm it fetched the new
   compose (via GitHub's rename redirect) and pulled `sentri-*`. This validates
   the load-bearing redirect assumption on device #1, not device #8.
4. **Flip the rest.** Repeat for the remaining devices. **Skip any device with a
   run in progress** — `up -d` recreates containers and would kill a live PCR
   run; flip it in a later pass.
5. **Verify.** On each device confirm
   `docker inspect --format '{{index .RepoDigests 0}}' ghcr.io/acorngenetics/sentri-api:prod`
   resolves to the latest published digest and that `RUNNING_IMAGE_DIGEST` in
   `/opt/fleet/.env` updated.
6. **Retire.** Once **all** devices report the new digest, stop dual-publishing
   and **delete** the old `aquilla-main-{api,ui}` GHCR packages. A frozen-but-
   resolvable package is exactly what silently strands a forgotten device, so it
   is removed, not left behind.

### Carve-outs (explicitly *not* renamed)

`AQ_` env vars and the `/opt/aquila` host state dir stay, for the operational
reasons above. The bare-metal systemd path (`config_files/aquila_app.service`,
`aquila_web/aquila_web.service`, the `/home/pi/aquilla-main` checkout) is
dev/legacy, not the production runtime; its files are renamed for tidiness but
need no coordinated field migration.

---

## Consequences

### Positive
- No device is ever pointed at a path that stops updating while still resolving
  — the Watchtower freeze trap is designed out, not hoped against.
- The canary catches a redirect failure on device #1.
- The fleet stays live throughout: an un-flipped device keeps running (and, for
  the dual-publish week, keeps updating) on the old path.
- Codebase is letter-perfect at the brand level (`aquila`/`aquilla` and `aq_`
  gone); the only residue is the intentionally-carved-out operational seams.

### Negative
- The cutover is hands-on, one device at a time over Tailscale SSH. Acceptable
  at 8 devices; would need a throwaway fan-out script at larger scale.
- The rename is largely irreversible once old GHCR packages are deleted —
  rollback during the window is repointing `GHCR_REPO`, not un-renaming.
- The rebrand is not *literally* total: `AQ_` and `/opt/aquila` still carry the
  codename. Anyone grepping `aq` still finds it. This is a conscious trade of
  tidiness for fleet safety, revisitable later (see `STATE_DIR`).

### Neutral
- Plan leans on GitHub's 301 redirects for `raw.githubusercontent.com` and
  `api.github.com` during the window; the canary verifies this.
- A future `/opt/aquila` → `/opt/sentri` migration remains available at roughly
  the same cost (a second per-device pass), made nearly free by `STATE_DIR`.

---

## Alternatives considered

- **Naive rename, let it ride.** Rejected: the Watchtower freeze trap silently
  strands the fleet with no error surface.
- **Pure dual-publish, no config flip.** Rejected: GHCR paths don't redirect, so
  devices never move to `sentri-*` on their own; dual-publish alone just delays
  the freeze.
- **Migrate `AQ_` env vars and `/opt/aquila` too (letter-perfect rebrand).**
  Rejected for now: converts a string-replace into a stateful per-device
  migration touching device identity, for no user-visible gain. A dual-read env
  shim (`SENTRI_* or AQ_*`) was considered as the bridge if this is revisited.
