# Greengrass Sentri Device — Setup & Onboarding

Bring up a new Sentri on AWS IoT Greengrass: bare Pi → a device that receives OTA
deployments **and** per-device Managed Profiles.

- Region `us-east-2`, account `867958227555`.
- Devices are reached over Tailscale SSH as `pi@<sn>`.
- **AWS credentials stay on the operator's machine — never on the Pi.**
- **Invariant:** cert CN == Device ID == Thing name == Pi serial. The scripts enforce it — don't override.

---

## Requirements

**Per device — have these ready:**
- Raspberry Pi on the network, powered on.
- GHCR read-only PAT (username `Acornadmin`) for image pulls.
- Operator AWS credentials (for enrollment + the console steps).
- Device values: hostname (`snXX`), image tag (`sandbox`/`dev`/`pilot`/`prod`), lid-heater
  bounds, drawer read_steps, Sentri number, `AQ_SYNC_ENDPOINT`, Grafana Cloud RW key.

**Fleet-level — one-time, already set up (verify only for a brand-new account):**
- acorn-ca registered with AWS IoT + JITP template (auto-creates the Thing, activates the
  cert, attaches `acorn-sentri-device`, lands it in the `holding` ring).
- `acorn-sentri-device` policy with shadow HTTP-sync enabled (**Appendix A**).
- TES role alias `acorn-sentri-tes`; Fleet Indexing on (`REGISTRY_AND_SHADOW` + named
  shadow `profiles`); rings whose deployments carry `com.acorn.sentri` +
  `com.acorn.profile-sync`.

---

## Step 1 — Tailscale bootstrap (on the Pi)

```bash
curl -fsSL "https://raw.githubusercontent.com/AcornGenetics/aquilla-main/main/scripts/setup/tailscale_bootstrap.sh" -o /tmp/tailscale_bootstrap.sh
sudo bash /tmp/tailscale_bootstrap.sh
```

Puts the Pi on the tailnet so you can reach it as `pi@<sn>`.

---

## Step 2 — Greengrass deployment (on the Pi)

```bash
curl -fsSL "https://raw.githubusercontent.com/AcornGenetics/aquilla-main/feat/greengrass-migration/scripts/deploy/deployment3_greengrass.sh" -o /tmp/deployment3_greengrass.sh
sudo bash /tmp/deployment3_greengrass.sh
```

In-place, no reflash, reversible (`--revert`). Builds the OS/hardware/kiosk/Docker stack,
generates the device keypair + CSR, and installs the Greengrass nucleus. Cert/keypair,
data-plane endpoint, boot ordering, and file perms are all handled automatically.

**Prompts:**

| Prompt | Value |
|---|---|
| `DEVICE_HOSTNAME` | `snXX` |
| `IMAGE_TAG` | `sandbox` / `dev` / `pilot` / `prod` |
| `GHCR_USER` | `Acornadmin` |
| `GHCR_TOKEN` | read-only GHCR PAT |
| `GHCR_TOKEN_2` | token key |
| `LID_HEATER_UPPER_BOUND` / `LOWER_BOUND` | e.g. `0.34` / `0.20` |
| `DRAWER_READ_STEPS` | e.g. `115` |
| `AQ_SYNC_ENDPOINT` | `https://ingest.cloud.acorngenetics.com/ingest` |
| `GCLOUD_RW_API_KEY` | Grafana Cloud RW API key |
| `TAILSCALE_KEY` | tailnet auth key (skipped if already joined) |

---

## Step 3 — Enroll the Device Certificate (operator machine)

```bash
cd aquilla-main
./scripts/enroll.sh <device>        # e.g. ./scripts/enroll.sh sn14
```

Signs the Pi's CSR against acorn-ca `/enroll` (SigV4 with your AWS creds), installs
`device.crt`, and verifies mTLS to `/renew`. It prints the CSR subject — confirm
`CN=<Pi-serial>`. Prod endpoints are the defaults; override with `ENROLL_ENDPOINT` /
`RENEW_ENDPOINT` for another environment.

Then restart the nucleus so it connects with the new cert:

```bash
ssh pi@<device> sudo systemctl restart greengrass
```

---

## Step 4 — Onboard the Thing (AWS Console)

On first connect JITP auto-registers the Thing (name = Device ID), activates the cert,
attaches `acorn-sentri-device`, and puts it in the `holding` ring. Everything below is in
the **AWS IoT Core** console.

### 4a. Confirm it registered
**Manage → All devices → Things** → search the Device ID.
- Not there after a minute? The device isn't connecting — recheck Steps 2–3.
- Open the Thing → **Certificates** tab: the cert should be **Active** and show
  `acorn-sentri-device` attached.
- **Greengrass devices → Core devices** → the device should be **Healthy**.

**If the cert is Inactive or has no policy (JITP half-fired):**
1. **Security → Certificates** → open the cert → **Actions → Activate**.
2. **Attach policy** → `acorn-sentri-device`.
3. **Attach to thing** → the Device ID.
4. If more than one cert is listed on the Thing, keep the active one and **deactivate/
   delete the extras** (stale certs cause version conflicts).

### 4b. Add the `Sentri_Number` searchable attribute
Open the Thing → **Edit** → **Searchable thing attributes – optional**:
- **Searchable attribute:** `Sentri_Number`
- **Value:** the Sentri number (e.g. `14`) → **Update**.

Lets you search/group the device by Sentri number in the console.

### 4c. Move it into a real ring (ONE ring per device)
Open the Thing → **Thing groups** tab.
1. Tick `holding` → **Remove**.
2. **Add to thing group** → pick the target ring (`dev` / `pilot` / `prod`) → **Add**.

Keep the device in **exactly one** ring — leaving a group does not drop its deployment.
Choose a ring whose deployment carries `com.acorn.sentri` **and** `com.acorn.profile-sync`,
or the device won't receive Managed Profiles.

---

## Step 5 — Assign Managed Profiles (AWS Console)

Once the device is in a ring that carries `com.acorn.profile-sync`, push Profiles to it
from the console — no device access needed.

**→ See [`assigning-managed-profiles.md`](./assigning-managed-profiles.md).**

In short: upload the profile to S3 under `profiles/<name>.json`, then add that key to the
Thing's **`profiles` named Device Shadow** (`desired`). It lands in `/opt/aquila/profiles/managed/`
within ≤5 min.

---

## Health checklist

- [ ] `enroll.sh` printed `✅ enrolled + verified`; CSR subject `CN=<serial>`.
- [ ] Thing exists; **one Active** cert with `acorn-sentri-device` attached.
- [ ] Core device **Healthy**; in **one** real ring (not `holding`); deployment succeeded.
- [ ] `profiles` shadow **reported** matches **desired** for assigned profiles.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Thing missing / cert Inactive / no policy | JITP half-fired → activate cert, attach `acorn-sentri-device`, attach to Thing (4a) |
| Shadow `reported` never catches up to `desired` (403) | shadow-sync authz / reconnect — Appendix A; quick fix: `ssh pi@<device> sudo systemctl restart greengrass` |
| Managed profile never lands | S3 key missing `profiles/` prefix or misspelled |
| New profile not shown in device UI | UI loads the list only on page load — reload the screen |
| Runs app but no Managed Profiles | device's ring deployment lacks `com.acorn.profile-sync` |
| mTLS 403 at `/ingest` & `/renew` | device cert expired → re-run `enroll.sh` |

---

## Appendix A — Shadow-sync authorization (background)

*One-time, fleet-wide, in IaC — operators don't touch this per device. Here so you know
where the §5c / Troubleshooting 403 lives.*

Greengrass ShadowManager syncs shadows over the **HTTPS IoT data plane using the device
cert**. So `acorn-sentri-device` must allow shadow actions with a variable that resolves
over HTTP, on both the classic and named-shadow ARNs:

```jsonc
"Resource": [
  "arn:aws:iot:*:*:thing/${iot:Certificate.Subject.CommonName}",     // classic
  "arn:aws:iot:*:*:thing/${iot:Certificate.Subject.CommonName}/*"    // named (profiles)
]
```

- Not `${iot:Connection.Thing.ThingName}` — MQTT-only, empty over HTTP → 403.
- The `/​*` ARN is required or the named `profiles` shadow 403s (acorn-fleet PR #34).
- Home: `acorn-fleet` `lib/registry-stack.ts` (`Acorn-Fleet-Registry`); `cdk deploy`.
- Policy changes take effect on **reconnect** — restart greengrass on an already-connected device.
