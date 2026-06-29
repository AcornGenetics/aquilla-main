# Enrolling a Sentri (Device Certificate)

How to get a newly-deployed Sentri its **Device Certificate** so it can Sync over
mTLS. This replaces the retired Fleet API Key (`AQ_SYNC_API_KEY`) — see ADR-013/014.

## The model in one paragraph

Each Sentri has its **own** keypair and a short-lived X.509 **Device Certificate**
issued by **acorn-ca**. The certificate's Subject `CN` is the **Device ID** (the Pi
hardware serial). The Pi generates its keypair + CSR locally — **the private key
never leaves the Pi** — and the **operator** (who holds AWS credentials) submits the
CSR to acorn-ca's `POST /enroll`. The Pi never holds AWS credentials, and never
holds anything that could mint *other* certificates.

```
Pi (deployment2.sh)            Operator workstation (AWS creds)        acorn-ca
  keypair + CSR (CN=serial)
  device.csr  ───────────────► enroll_device.py
                                  POST /enroll (SigV4) ──────────────► issues leaf
  device.crt 0600  ◄──────────── installs cert + device.env (over SSH)  (CA-signed)
```

## Prerequisites

- The Sentri is deployed (`scripts/deploy/deployment2.sh` has run) — so
  `/opt/aquila/config/device.csr` exists and Tailscale SSH is up.
- You can `ssh <pi>` to it (Tailscale hostname or IP).
- **AWS credentials** on your workstation with permission to invoke the enroll API
  (`execute-api:Invoke` on the acorn-ca `/enroll` route). Never put these on the Pi.
- The acorn-ca **enroll endpoint URL** for the target environment. Find it with:
  ```bash
  aws apigatewayv2 get-apis \
    --query "Items[?Name=='EnrollApi'].ApiEndpoint" --output text
  # → https://<id>.execute-api.us-east-2.amazonaws.com   (append /enroll)
  ```
- A local checkout of this repo with `botocore` + `cryptography` installed
  (`pip install -r requirements-test.txt` covers both).

## Enroll

From your workstation (not the Pi):

```bash
python scripts/enroll_device.py \
    --pi sn04 \
    --endpoint https://<id>.execute-api.us-east-2.amazonaws.com/enroll \
    --region us-east-2
```

This:
1. SSH-reads the CSR (`/opt/aquila/config/device.csr`) off the Pi.
2. SigV4-signs a POST of the CSR to `/enroll` with **your** AWS identity.
3. SSH-writes the issued certificate to `/opt/aquila/config/device.crt` (`0600`).
4. Rewrites `/opt/aquila/config/device.env`: adds `AQ_SYNC_CLIENT_CERT` /
   `AQ_SYNC_CLIENT_KEY` and removes any stale `AQ_SYNC_API_KEY`.

Success prints `enrolled <pi>: certificate installed at /opt/aquila/config/device.crt`.

## Verify (optional, runs on the Pi)

Once the prod renew domain is live (`renew.cloud.acorngenetics.com`), confirm the
certificate authenticates over mTLS — no AWS credentials needed, the cert is the
credential:

```bash
ssh <pi> 'cd /opt/aquila && set -a && . config/device.env && \
  python scripts/verify_device_cert.py \
    --renew-endpoint https://renew.cloud.acorngenetics.com/renew'
# PASS: Device Certificate authenticated over mTLS to /renew
```

A missing / expired / wrong-CA certificate fails the TLS handshake and reports `FAIL`.

## What changed in `deployment2.sh`

The deploy script no longer touches a shared key; it sets up the device *identity*
and generates the CSR. Three edits:

1. **`DEVICE_ID` is the Pi hardware serial, not the hostname** (Phase 8).
   Was `DEVICE_ID=${DEVICE_HOSTNAME}` (e.g. `sn04`). Now it reads the serial from
   `/proc/cpuinfo` and **fails loud** if there isn't one — so the Device Certificate's
   `CN` matches what the platform treats as the Device ID (the serial survives
   reimages; the hostname doesn't). `DEVICE_HOSTNAME` is still written separately for
   hardware config (`host_config.json`).

2. **Keypair + CSR generated on-device** (Phase 9, after the image pull).
   A `docker run … python -m aq_lib.device_csr /config` produces
   `device.key` (`0600`) + `device.csr` with `CN=<serial>`. It runs **in the app
   image** because the host has no crypto deps, and mounts `/proc/cpuinfo` read-only so
   the container derives the **same** serial. Two `run_test` checks assert the CSR
   exists and the key is owner-only.

3. **Fleet API Key removed.** The `AQ_SYNC_API_KEY` prompt and its `device.env` line
   are gone — the Sentri authenticates Sync with its Device Certificate instead.

The deploy script does **not** enroll — enrollment is the operator step above, because
it needs AWS credentials that must never land on the Pi.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `enrolment failed: … HTTP 403 … is revoked` | The Device ID is revoked in acorn-ca. It will not be issued a cert — investigate the device before un-revoking. |
| `enrolment failed: … HTTP 400 malformed Device ID` | The CSR `CN` isn't a valid Pi serial. Check Phase 8 didn't fall back / the Pi has a real serial. |
| `no AWS credentials on this machine` | You ran the enroll tool without AWS creds. Authenticate your workstation (the Pi must stay credential-free). |
| `ssh: … device.csr: No such file` | Deployment didn't reach Phase 9, or the image lacks `aq_lib`. Re-run `deployment2.sh`. |
| Verify `FAIL` / handshake rejected | Cert missing/expired/wrong-CA, **or** you're hitting an endpoint without mTLS (only the prod `renew.cloud…` custom domain enforces it; the default `execute-api` URL does not). |

## Related

- acorn-ca `CONTEXT.md` — Enrollment, Renewal, Revocation, Cohort definitions.
- `specs/prd/kms-ca-enrollment-mtls-s3-verification-prd.md` (Rev 2) — the slice spec.
- Renewal (automatic, before expiry) and the offline re-enrollment fallback are a
  later slice; this covers first-time enrollment.
