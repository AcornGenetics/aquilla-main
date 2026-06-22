# PRD: aquila → sentri rebrand — code, CI/CD, and fleet cutover

_Published to the tracker as [#185](https://github.com/AcornGenetics/aquilla-main/issues/185). Tracks #178. Decisions captured in ADR-016 (`docs/adr/ADR-016-aquila-to-sentri-rebrand-cutover.md`) and the glossary in `CONTEXT.md`._

## Problem Statement

"Aquila" was the internal pre-launch codename for the PCR instrument; the product brand is **Sentri** — the device already *is* a Sentri in our own glossary, but the code, repo, CI/CD, and deployment pipeline still say `aquila`/`aquilla` (~1,116 occurrences across 155 files). Operators and engineers see a stale codename everywhere, and the mismatch between brand and code is a continual source of confusion.

A naive "rename the repo and find-replace `aquila`" is dangerous: the production fleet is Docker-based with Watchtower auto-updates, and **GHCR package paths do not redirect on a repo rename**. A blind rename would leave every field device's Watchtower silently stuck on the frozen pre-rebrand image forever — no error, no new releases. The deployment scripts also contain dozens of cross-referenced names and paths (container DNS names, service-unit filenames, image paths) where a half-completed rename breaks the device only at runtime.

## Solution

Do the full code/CI rename so the codebase catches up to the **Sentri** brand, but execute the fleet cutover with a **config-push-first, dual-publish** sequence that never points a device at a path which stops receiving updates while still resolving. Deliberately carve out the operational seams (`AQ_` env vars, the `/opt/aquila` host state directory) that are stateful contracts with the live fleet, so the rename stays a code change rather than a risky per-device data migration. Protect the highest-risk surface — the deployment pipeline — with static integrity tests that catch half-completed renames before they ship.

From the user's perspective: the repo becomes `AcornGenetics/sentri`, `docker ps` shows `sentri-*` containers, the code reads `sentri_web`/`sentri_lib`/`sentri_curve`, and the 8-device fleet is migrated to the new image path with zero silent breakage and no interrupted PCR runs.

## User Stories

1. As an engineer, I want the repository renamed to `AcornGenetics/sentri`, so that the repo name matches the product brand.
2. As an engineer, I want all `aquila`/`aquilla` string occurrences replaced with `sentri` (preserving casing: `aquila→sentri`, `Aquila→Sentri`, `AQUILA→SENTRI`, `aquilla→sentri`, `Aquilla→Sentri`), so that the codebase no longer carries the codename.
3. As an engineer, I want the `aquila_web/` directory and app renamed to `sentri_web/` with all internal imports, path references, and string literals updated, so that the web application reflects the brand.
4. As an engineer, I want the `aq_lib` and `aq_curve` packages renamed to `sentri_lib` and `sentri_curve` with all `import`/`from` statements and dynamic `importlib.import_module(...)` strings updated, so that no `aq_` source prefix remains.
5. As an engineer, I want `docs/aquila_web/` renamed to `docs/sentri_web/` (and `aquila_web_overview.md` → `sentri_web_overview.md`), so that documentation paths match the code.
6. As a developer, I want the test suite's imports updated (`from sentri_web import main`, `sentri_lib`, `sentri_curve`), so that the existing tests still exercise the renamed code.
7. As a release engineer, I want CI (`docker-build.yml`, `promote-images.yml`) to publish images to `ghcr.io/acorngenetics/sentri-{api,ui}` automatically via `$GITHUB_REPOSITORY`, so that the first post-rename build lands on the new path.
8. As a release engineer, I want the hardcoded image defaults in `docker/docker-compose.yml` and `fleet-config/docker-compose.yml` changed from `acorngenetics/aquilla-main` to `acorngenetics/sentri`, so that a device without an explicit `GHCR_REPO` resolves the correct image.
9. As a release engineer, I want CI to **dual-publish** to both `aquilla-main-*` and `sentri-*` for one release cycle (~1 week) after the rename, so that any not-yet-flipped device keeps receiving updates during the cutover window.
10. As a fleet operator, I want a documented per-device cutover runbook (canary → flip → verify → retire), so that I can migrate all 8 devices over Tailscale SSH without bricking any.
11. As a fleet operator, I want to flip one canary device first (set `GHCR_REPO=acorngenetics/sentri` in `/opt/fleet/.env`, run `fleet-update.sh`), so that I validate GitHub's rename redirect on device #1 rather than device #8.
12. As a fleet operator, I want to skip any device with a run in progress during the flip, so that `up -d` does not interrupt a live PCR run.
13. As a fleet operator, I want to verify each device reports the new `sentri-api:prod` digest in `RUNNING_IMAGE_DIGEST`, so that I know the flip succeeded before retiring the old path.
14. As a fleet operator, I want the old `aquilla-main-{api,ui}` GHCR packages deleted only after all 8 devices confirm the new digest, so that no forgotten device is silently stranded on a frozen package.
15. As a release engineer, I want a tracked checklist item to remove the temporary dual-publish CI step after retirement, so that the transitional workaround does not linger.
16. As an engineer, I want the `AQ_` environment variables (e.g. `AQ_SYNC_DEVICE_ID`, `AQ_SYNC_ENDPOINT`, `AQ_SRC_BASEDIR`) left unchanged, so that the cert-bound device identity and fleet env contract are not broken by the rename.
17. As an engineer, I want the `/opt/aquila` host state directory left unchanged, so that each device's `device.env`, calibration, results, and logs are not lost.
18. As an engineer, I want the compose bind-mount paths parameterized behind a `STATE_DIR` variable (default `/opt/aquila`), so that a future migration to `/opt/sentri` is a one-line env change rather than a compose rewrite.
19. As an engineer, I want the `container_name` values renamed to `sentri-{backend,app,ui,watchtower}`, so that the brand shows in `docker ps`.
20. As an engineer, I want every service-DNS reference (`BACKEND_URL`, `WATCHTOWER_URL`, `nginx.conf` `proxy_pass`, `entrypoint.sh` defaults) updated in lockstep with the renamed `container_name`s, so that the UI can still reach the backend at runtime.
21. As an engineer, I want the systemd unit files renamed (`aquila_app.service` → `sentri_app.service`, `aquila_web/aquila_web.service` → `sentri_web/sentri_web.service`) and every deploy-script reference to them updated in lockstep, so that the `[[ -f ... ]]` guards do not silently skip installing them.
22. As a fleet operator, I want `verify_fleet_device.sh` and `deployment2_verify.sh` updated to assert the new `sentri-*` container names and unit names, so that post-cutover verification passes instead of failing on stale names.
23. As an engineer, I want the mixed keep/rename files (especially `docker/entrypoint.sh`) edited selectively — `/opt/aquila` paths preserved, `aquila-backend` DNS names renamed — so that a blind replace does not corrupt the carve-out.
24. As a developer, I want a deployment-pipeline test that asserts every `http://NAME:PORT` reference resolves to a declared container, so that a half-renamed `container_name` is caught in CI, not in the field.
25. As a developer, I want a test that asserts every `*.service` filename referenced in deploy scripts exists in the tree, so that a renamed unit with a stale script reference fails CI.
26. As a developer, I want a test that asserts compose image defaults resolve to `acorngenetics/sentri-{api,ui}` and CI uses the `$GITHUB_REPOSITORY`-derived path, so that the freeze-trap default cannot regress.
27. As a developer, I want a selective-rename guard that asserts `/opt/aquila` and `AQ_` tokens are preserved while brand DNS/image tokens are renamed, so that the ADR-016 scope is an executable invariant.
28. As a developer, I want a test that asserts bind mounts use `${STATE_DIR:-/opt/aquila}`, so that the parameterization preserves current behavior.
29. As a developer, I want a repo-wide completeness guard asserting no residual `aquila`/`aquilla`/`aq_lib`/`aq_curve` tokens except the documented carve-outs, so that the rename is provably complete.
30. As an engineer, I want the glossary (`CONTEXT.md`) to define **Sentri** as the brand and **Aquila** as the retired codename surviving only in the `AQ_` prefix, so that future readers understand the carve-outs.
31. As an engineer, I want the bare-metal systemd path and `/home/pi/aquilla-main` checkout treated as dev/legacy — renamed for tidiness but with no coordinated field migration — so that effort focuses on the real production (Docker) runtime.
32. As an engineer, I want scripts and config (`config.json`, `compose.yaml`, `infra/.aws-sam/build.toml`, `config_files/host_config.json`, `docker/entrypoint.sh`, `scripts/setup/*`, `scripts/deploy/*`) updated, so that no deployment artifact references the old name except the carve-outs.

## Implementation Decisions

- **Scope, in:** all `aquila`/`aquilla` strings; `aquila_web` → `sentri_web`; `aq_lib`/`aq_curve` → `sentri_lib`/`sentri_curve` (no packaging metadata exists — they resolve via `PYTHONPATH`, so renaming is pure source plus the dynamic `importlib` strings); `container_name`s → `sentri-*`; systemd unit filenames; docs paths.
- **Scope, deliberately out (operational carve-outs, per ADR-016):** the `AQ_` environment-variable prefix (values are set in each device's environment; `AQ_SYNC_DEVICE_ID` is cert-bound identity) and the `/opt/aquila` host state directory. Renaming either converts a string-replace into a stateful per-device migration for zero user-visible benefit.
- **`STATE_DIR` insurance:** parameterize the compose bind-mount host paths behind `${STATE_DIR:-/opt/aquila}` so a future `/opt/sentri` migration is a one-line env change. Default preserves current behavior exactly.
- **CI image path:** `docker-build.yml`/`promote-images.yml` derive `REPO_LOWER` from `$GITHUB_REPOSITORY`, so published images follow the rename automatically. The two hardcoded compose defaults (`acorngenetics/aquilla-main`) do **not** follow and must be edited to `acorngenetics/sentri`.
- **Cutover sequence (config-push-first):** rename repo → dual-publish both image paths for ~1 week → canary one device → flip remaining 7 (`GHCR_REPO=acorngenetics/sentri` in `/opt/fleet/.env` + `fleet-update.sh`, skipping mid-run devices) → verify each device's `RUNNING_IMAGE_DIGEST` → delete old GHCR packages → remove dual-publish CI step. `GHCR_REPO` (in `/opt/fleet/.env`) is the single control point for image namespace, the `raw.githubusercontent.com` compose fetch, and the `api.github.com` token check.
- **Redirect dependency:** the cutover leans on GitHub 301-redirecting renamed-repo requests for `raw.githubusercontent.com` and `api.github.com` (GHCR does **not** redirect, which is why `GHCR_REPO` is flipped). The canary validates this.
- **Cross-reference invariants (the high-risk surface):** (1) `container_name` ↔ service-DNS refs (`BACKEND_URL`, `WATCHTOWER_URL`, `nginx.conf`, `entrypoint.sh`); (2) `*.service` filenames ↔ deploy-script references guarded by `[[ -f ]]`; (3) compose image default ↔ CI publish path ↔ `fleet-update.sh` digest inspect; (4) mixed keep/rename within a single file (`entrypoint.sh` holds both `/opt/aquila` and `aquila-backend`). `verify_fleet_device.sh` and `deployment2_verify.sh` must be updated to assert the new names or they fail every post-cutover verification.
- **Glossary:** `CONTEXT.md` already updated — **Sentri** = brand, **Aquila** = retired codename surviving only in `AQ_`/`/opt/aquila`.

## Testing Decisions

A good test here asserts **external/structural behavior** — that the deployment artifacts are internally consistent and the renamed code still runs — not implementation details of any one script. Tests are static (parse YAML / scan scripts) or use the existing FastAPI `TestClient`; none require a real Pi or network, so all run in CI.

**Modules / surfaces tested:**

- **The full existing suite (`pytest tests unit_tests`)** is the highest seam and the real proof the code rename is behavior-preserving: once `tests/conftest.py` imports `from sentri_web import main` and the `sentri_lib`/`sentri_curve` packages resolve, the `unit`/`contract`/`state` tests pass unchanged. Prior art: `tests/conftest.py` (`TestClient(web_main.app)`), `tests/contract/*`.
- **Deployment-pipeline tests** (new, in `tests/fleet_device/`):
  - **D1 — compose DNS integrity:** every `http://NAME:PORT` in compose env values, `docker/nginx.conf`, and `docker/entrypoint.sh` resolves to a declared `container_name`/service. A *permanent* guard, valuable beyond the rebrand.
  - **D2 — service-unit reference integrity:** every `*.service` filename referenced in `scripts/deploy/*.sh` (including `verify_fleet_device.sh`, `deployment2_verify.sh`) exists as a unit file in the tree.
  - **D3 — image-path agreement:** compose image defaults parse to `acorngenetics/sentri-{api,ui}`; CI uses the `$GITHUB_REPOSITORY`-derived path with no hardcoded old name.
  - **D4 — selective-rename guard:** across deploy files, `/opt/aquila` and `AQ_` occurrences are preserved while brand DNS/image tokens are renamed.
  - **D5 — STATE_DIR parameterization:** bind mounts use `${STATE_DIR:-/opt/aquila}`; default preserves `/opt/aquila`.
  - D1/D2 scopes explicitly include `verify_fleet_device.sh` and `deployment2_verify.sh`.
- **Repo-wide completeness guard** (new, `unit`): walks tracked files and asserts no residual `aquila`/`aquilla`/`aq_lib`/`aq_curve` tokens except the documented carve-outs (`AQ_` env vars, `/opt/aquila` paths). Prior art for the grep/walk pattern: `tests/unit/test_diagnose.py`, `tests/unit/test_wifi_helpers.py`.

**Not tested (deliberately):** the live fleet cutover (canary, dual-publish, per-device flip, digest verification, package retirement) — these touch Tailscale/GHCR/Watchtower and are verified by the runbook's canary + digest checks, not CI. Fixed vendor strings (the watchtower `enable` label), secret values (`WATCHTOWER_HTTP_API_TOKEN`), and the unchanged kiosk port (`8090`, not a brand name) are not name-coupled and are left untested.

## Out of Scope

- Renaming the `AQ_` environment variables or the `/opt/aquila` host state directory (operational carve-outs; revisitable later via a dual-read env shim and the `STATE_DIR` parameterization).
- Any change to the separate **Sentri Analytics Platform** (`Acorn/sentri-analytics`) — this PRD is the device-edge repo only.
- The in-flight mTLS / KMS-CA device-PKI migration (ADR-013, ADR-014) — independent work; this rebrand must not regress it.
- Automated testing of the live fleet cutover (operational runbook, not CI).
- A coordinated bare-metal systemd field migration — that path is dev/legacy; its files are renamed for tidiness only.

## Further Notes

- The fleet is **8 devices**, accessed manually via Tailscale SSH; there is no fleet-wide orchestrator, so the cutover is a hand-driven runbook (acceptable at this scale; a throwaway fan-out script would only be warranted at larger scale).
- `deployment2.sh` is the real provisioner that writes `GHCR_REPO` into `/opt/fleet/.env`; `setup_fleet_device.sh` is the older/simpler one that omits it.
- The mTLS Device Certificate is **not yet** deployed (the fleet is still on `AQ_SYNC_API_KEY`); when it lands it will live under `/opt/aquila/config`, which is another reason to keep that path stable.
- ADR-016 is the authoritative decision record; this PRD operationalizes it into stories and tests.
