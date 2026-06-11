# ADR-010: Migrate Repository to Private with Authenticated Raw File Access

**Status:** Proposed
**Date:** 2026-06-11
**Author:** Nicole Cornell
**Deciders:** Nicole Cornell

---

## Context

The `acorngenetics/aquilla-main` GitHub repository is currently public. Moving it to private protects IP in source code and container images. Several deployment and OTA update mechanisms download files directly from `raw.githubusercontent.com`, and this access pattern must continue to work after the repo goes private.

- Devices authenticate to GHCR using a PAT stored in `/opt/aquila/config/device.env` as `GHCR_TOKEN`
- The current token (`Aquila-read-only`) has only `read:packages` scope — sufficient for image pulls but insufficient for reading raw file content from a private repo
- `deployment2.sh` and `fleet-update.sh` already use `Authorization: token ${GHCR_TOKEN}` on some `curl` calls, but not all
- GHCR container images are already private

---

## Decision

**We will make the repository private and use a fine-grained PAT with `Contents: Read` + `Packages: Read` scopes (scoped to `aquilla-main` only) for all device and bootstrap authentication.**

Concrete changes required before flipping the repo to private:

1. **Create new fine-grained PAT** — `Contents: Read` + `Packages: Read`, scoped to `aquilla-main`, no expiration (or with rotation plan). Store in team password manager.

2. **Add auth headers to unauthenticated `curl` calls in `deployment2.sh`** — these four calls use `${RAW_REPO_URL}` without a token and will fail once the repo is private:
   - Line 222–224: `splash.html`
   - Line 735: `kiosk_control.py`
   - Line 742: `wifi_recovery.sh`
   - Lines 936–939: Plymouth boot theme files (`acorn.plymouth`, `acorn.script`)

3. **Update all deployed devices** — in-house devices can be re-provisioned directly. For the field device, update via Tailscale SSH:
   ```bash
   sudo sed -i "s|^GHCR_TOKEN=.*|GHCR_TOKEN=<new-token>|" /opt/aquila/config/device.env
   grep GHCR_TOKEN /opt/aquila/config/device.env | cut -d= -f2 \
     | sudo docker login ghcr.io -u <ghcr-username> --password-stdin
   sudo docker restart watchtower
   ```
   Only watchtower needs restarting — it is the only container that uses Docker registry credentials for image pulls.

4. **Update bootstrap procedure** — new device setup requires the technician to supply the token in the initial `curl` call:
   ```bash
   curl -fsSL \
     -H "Authorization: token <PAT>" \
     https://raw.githubusercontent.com/acorngenetics/aquilla-main/main/scripts/deploy/deployment2.sh \
     | sudo bash
   ```

**Safe rollout order:** fix code → merge → update devices → flip repo private.

---

## Consequences

### Positive
- Source code and deployment scripts are no longer publicly readable
- Blast radius of a compromised device token is limited to one repo (fine-grained PAT)

### Negative
- New device bootstrap requires a token to be supplied out-of-band before running `deployment2.sh`
- Token rotation requires updating all deployed devices

### Neutral / Tradeoffs
- CI/CD workflows (`docker-build.yml`, `promote-images.yml`) are unaffected — `secrets.GITHUB_TOKEN` works for private repos
- `fleet-update.sh` already has auth headers — no changes needed there

---

## Alternatives Considered

### Option A: Classic PAT with `repo` scope
**Why rejected:** Grants read access to all private repos in the org, not just `aquilla-main`. Excess privilege on deployed devices.

### Option B: Deploy a public bootstrap script that fetches from a separate private repo
**Why rejected:** Unnecessary complexity. The existing `curl | bash` pattern with a token header is already used internally and works.

---

## Revisit Conditions

- If the fleet grows beyond ~20 devices, a secrets management system (e.g., Vault, AWS Secrets Manager) should replace per-device token distribution
- If GitHub deprecates fine-grained PATs or changes raw content auth, revisit token type

---

## References

- Related ADRs: ADR-002 (Watchtower fleet updates)
- `scripts/deploy/deployment2.sh` — lines requiring auth header fixes: 222, 735, 742, 936–939
- `scripts/deploy/fleet-update.sh` — already correct, no changes needed
