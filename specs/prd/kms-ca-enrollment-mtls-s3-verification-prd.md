# PRD: Device-side enrollment + mTLS cert verification slice (client of acorn-ca)

> **Tracking issue:** [#176](https://github.com/AcornGenetics/aquilla-main/issues/176)
> **Revision 2 — 2026-06-26** (supersedes Rev 1, 2026-06-17)
>
> **What changed in Rev 2 — the six-repo split.** Rev 1 was written when aquilla-main
> was a monolith: it had aquilla-main *bootstrap the CA*, *host the signing path*, and
> *enable mTLS on its own SAM `HttpApi`* (`infra/template.yaml`), gated by an
> **enrollment password**. That server side has since moved out and is **built and proven live**:
> - **acorn-ca** owns the CA (KMS key + S3 truststore), the **`POST /enroll`** endpoint
>   (operator-authenticated via **AWS SigV4/IAM**, *not* a password — ADR-0001), and the
>   **`POST /renew`** mTLS endpoint.
> - **acorn-analytics** owns the **Ingest Endpoint** (the Sync target) — *not yet built*.
>
> So aquilla-main is now **client-only**: it hosts **no endpoints**. This slice is the
> on-device code that *calls out* to acorn-ca's endpoints — generate a keypair + CSR on
> the Pi, get it enrolled, install the cert, present it over mTLS, and swap Sync off the
> Fleet API Key. Anchored by **ADR-014** (device PKI) and **ADR-013** (device auth → mTLS).
> Glossary in `CONTEXT.md`. acorn-ca's contract is in its `CONTEXT.md` + ADRs 0001–0006.

## Problem Statement

ADR-014's PKI is now real *on the CA side* — acorn-ca stands up a KMS-backed CA, issues
short-lived per-device certificates via `POST /enroll` (operator SigV4), and renews them via
`POST /renew` (mTLS). All of that is deployed and proven end-to-end.

But **no Sentri can use it yet.** On the device today:

- there is no on-Pi step to **generate a keypair + CSR** (`CN=<Device ID>`) during deployment,
- there is no step to **submit that CSR to acorn-ca `/enroll`** and **install** the returned
  certificate + key,
- `deployment2.sh` still prompts for and writes the retired shared **`AQ_SYNC_API_KEY`**, and
  `aquila_web/sync.py` still authenticates Sync with an `x-api-key` header instead of a client
  certificate,
- there is no way to **verify** that a freshly enrolled certificate actually authenticates over
  mTLS.

Until a deployed Sentri can get a certificate from acorn-ca and prove it authenticates over
mTLS, the device half of ADR-014 is unproven and the rest of the migration (renewal, Sync
cutover, decommission) has nothing to build on.

## Solution

From the operator's and the fleet's perspective — **device side only**:

- **Deploying a Sentri gets it a certificate.** During `deployment2.sh` the Sentri generates
  its own keypair on-device and a CSR with `CN=<Device ID>` (Device ID = the Pi hardware serial,
  per `aq_lib/device_id.py` and `CONTEXT.md`). The CSR is submitted to acorn-ca **`POST /enroll`**.
  The returned certificate and the device key land on the Pi `chmod 600`, with their paths
  recorded in `device.env`. The device's private key never leaves the Pi.
- **The gate is the operator's AWS identity, not a password.** `/enroll` is **SigV4/IAM**-authorized
  (acorn-ca, ADR-0001), so the enroll call must be made by someone holding operator AWS credentials.
  The Pi holds **no** AWS credentials and **no** credential that could mint *other* certificates —
  it only ever holds its own keypair + leaf. (See *Implementation Decisions → Where the enroll call
  runs* for the operator-mediated flow this implies.)
- **The shared Fleet API Key is gone.** Deployment stops prompting for / writing `AQ_SYNC_API_KEY`;
  `sync.py` drops the `x-api-key` header and presents the Device Certificate (client cert + key) on
  the Sync POST instead.
- **I can verify the certificate works.** A device-side verification script presents the Device
  Certificate over **mTLS to acorn-ca `POST /renew`** and confirms the handshake succeeds (HTTP 200).
  A missing / expired / wrong-CA certificate fails the TLS handshake and gets nothing. That is the
  proof the certificate is CA-valid and that mTLS is actually enforced. *(Proving a real **Event**
  lands in storage is the acorn-analytics Ingest Endpoint's job and waits on that edge — see Out of
  Scope. `/renew` is the available, production-shaped mTLS target today.)*

## User Stories

1. As a Sentri, I want to generate my own keypair on-device during deployment, so that my private key never leaves the Pi.
2. As a Sentri, I want to build a CSR with `CN=<Device ID>` (the Pi hardware serial), so that my transport identity equals my data-model identity.
3. As an operator, I want `deployment2.sh` to submit the CSR to acorn-ca `POST /enroll` using my AWS credentials (SigV4), so that issuance is gated by my AWS identity and no on-device secret can mint certificates.
4. As a Sentri, I want my returned certificate and private key written `chmod 600`, so that they are not world-readable on the device.
5. As a Sentri, I want the certificate and key paths recorded in `device.env`, so that the Sync client and verification script can find them.
6. As an operator, I want enrollment to fail loudly (non-zero exit, clear message) on an auth or signing error, so that a deployment never silently completes without a valid certificate.
7. As an operator, I want `deployment2.sh` to stop prompting for and writing `AQ_SYNC_API_KEY`, so that the retired shared-key model is removed from new deployments.
8. As a Sentri, I want to present my Device Certificate (client cert + key) on the Sync POST instead of an `x-api-key` header, so that I authenticate by mTLS.
9. As an operator, I want a device-side verification script that presents the certificate over mTLS to acorn-ca `/renew`, so that I can confirm the certificate authenticates and mTLS is enforced.
10. As an operator, I want the verification to fail when no certificate, an expired certificate, or a wrong-CA certificate is presented, so that I know the gateway is actually enforcing mTLS and not accepting anything.
11. As a developer, I want the CSR-subject construction (`CN=Device ID`) extracted as pure logic, so that it is unit-testable without hardware.
12. As a developer, I want the device Sync auth change covered by the existing Sync test seam, so that "certificate sent, no `x-api-key`" is verified automatically.
13. As a developer, I want the Device ID derivation reconciled to the Pi hardware serial (not the hostname) wherever the CSR `CN` is built, so that the device's `CN` matches what the platform treats as the Device ID.

## Implementation Decisions

### Where the enroll call runs (operator-mediated) — *the key Rev-2 design point*
`/enroll` is SigV4-authorized, and **the Pi has no AWS credentials by design** — so the Pi cannot
call `/enroll` itself. Enrollment is therefore **operator-mediated**: the Pi produces the
keypair + CSR, the **operator** (running with their AWS credentials) submits the CSR to `/enroll`,
and the returned certificate is installed back onto the Pi. Concretely, `deployment2.sh` is run by
the operator during provisioning in a context where AWS credentials are available (e.g. the operator's
session/host), generating the CSR and orchestrating the enroll → install. **The private key never
leaves the Pi and AWS credentials never land on the Pi.** *(This is the central change from Rev 1's
password model, which the Pi could complete unattended — confirm before building.)*

### On-device keygen + CSR (`deployment2.sh`)
- The Sentri generates its own keypair and a CSR with `CN=<Device ID>`. **Device ID is the Pi hardware
  serial** (`aq_lib/device_id.py` → `/proc/cpuinfo`), *not* the hostname. `deployment2.sh` currently
  derives `DEVICE_ID` from the hostname — reconcile it to the serial so the CSR `CN` matches the
  platform identity (acorn-ca treats the cert `CN` as the Device ID).
- The pure logic (CSR subject construction = `CN=Device ID`) is extracted into Python so it is
  unit-testable; the on-device keygen/install steps are host-dependent.

### Enroll + install
- Submit CSR to acorn-ca **`POST /enroll`** with SigV4. On success, write the returned certificate and
  the device key `chmod 600` and record their paths in `device.env`. Enrollment failure (auth error,
  signing error, revoked Device ID → 403) **exits non-zero with a clear message** — no silent completion.
- Stop prompting for / writing `AQ_SYNC_API_KEY`; remove the Fleet API Key from new deployments.

### Device Sync auth (`aquila_web/sync.py`)
- The Sync client **drops the `x-api-key` header** and presents the **client certificate + key** on the
  POST (`cert=(client_cert, client_key)` style). Certificate/key paths come from `device.env`. The Event
  payload shape is **unchanged** (still keyed on `device_id`). *(The live Sync target is acorn-analytics'
  Ingest Endpoint, which is not built yet — this slice lands the client-side auth change and unit-tests
  it; the live Sync-to-storage acceptance is gated on that edge.)*

### Verification script
- A device-side script loads the Device Certificate from `device.env` and **POSTs over mTLS to acorn-ca
  `POST /renew`**, asserting a successful handshake (HTTP 200). Negative cases (no cert / expired /
  wrong-CA) must fail the handshake and return nothing. This is the available, production-shaped mTLS
  proof until the acorn-analytics ingest edge exists.

## Testing Decisions

Assert **external behavior at the highest available seam** — what the device puts on the wire, and the
pure CSR-subject logic — not internal call order. Mock the network boundary (`requests.post`) rather
than reaching real services in unit tests.

- **Device Sync auth — existing seam (`POST /sync/flush` → `aquila_web.sync`).** Prior art:
  `tests/unit/test_background_sync.py` (monkeypatches `aquila_web.sync.requests.post`, captures call
  kwargs). Replace the `x-api-key` assertion with: the client-certificate tuple is passed and **no**
  `x-api-key` header is present. Keep "no endpoint → synced 0" and "network error swallowed, events
  stay pending" green.
- **CSR subject construction.** Pure-logic unit test (`unit_tests/`): given a Device ID, the CSR subject
  is `CN=<Device ID>`. Prior art: `tests/unit/test_device_id.py`.
- **Enrollment / on-device keygen + install.** Host-dependent (keygen, install, `deployment2.sh`) — mark
  `@pytest.mark.hardware` with a documented "why not CI" note per the repo testing rules; cover the
  extractable pure logic (CSR subject, Device ID = serial) above.
- **End-to-end acceptance (the real proof).** Against a **live acorn-ca**: from a Sentri enrolled via
  `/enroll`, the verification script presents the cert over mTLS to `/renew` and gets HTTP 200;
  presenting no / expired / wrong-CA certificate fails the handshake.
- **CA bootstrap / signing / truststore / gateway-mTLS tests are no longer in this repo** — they live in
  **acorn-ca** (which owns and tests them). Do not re-create them here.

## Out of Scope

Owned by **acorn-ca**, **acorn-analytics**, or later aquilla-main slices — **not** this slice:

- **The entire CA + signing side** — KMS key, root cert, truststore publish (C1), `/enroll`, `/renew`,
  the revocation feed (C2), enrollment-password logic. Owned and proven in **acorn-ca**.
- **The Ingest Endpoint and the live Sync-to-storage proof** (mTLS gateway → S3/RDS) — owned by
  **acorn-analytics** (ADR-015), not yet built. This slice verifies the certificate against acorn-ca
  `/renew`; the full Event-into-storage acceptance follows once that edge exists.
- **Automatic certificate renewal** — the on-device renewal daemon (daily attempt, atomic swap when
  <3 days remain) and the offline-too-long **re-enrollment** fallback. Next aquilla-main slice.
- **Decommissioning** the old SAM ingest stack and the big-bang fleet cutover.
- Any Event payload schema change (this slice is auth-only); backfill-tool auth change; any dev-fleet
  certificate isolation (one prod fleet, one CA).

## Dependencies / Preconditions

- **acorn-ca deployed and live** — `/enroll` + `/renew` reachable. *(Currently neither dev nor prod is
  deployed; only the CI/CD stack exists. A dev redeploy or the prod deploy (#25) is required before the
  acceptance test can run. Code + unit tests can be built now against mocks.)*
- **Operator AWS credentials** available wherever the enroll call is made (for SigV4).
- The `renew.cloud.acorngenetics.com` mTLS domain (prod) or the dev equivalent, depending on which
  acorn-ca environment is live.

## Further Notes

- This is the **smallest end-to-end runnable proof** of the *device half* of ADR-014 in the post-split
  world: keypair/CSR on the Pi → operator-mediated enroll against acorn-ca → certificate installed →
  mTLS handshake proven. Everything in scope can be built and unit-tested now against mocks; the
  **acceptance test** needs a live acorn-ca.
- BUILD.md sequences **acorn-analytics' ingest edge before** aquilla-main's device side precisely because
  the device's ultimate Sync target lives there. Building the "get a cert + verify via `/renew`" half now
  is fine and de-risks the device code; the live Sync proof waits on that edge.
- The short-validity posture is acceptable here because this slice doesn't auto-renew — certificates are
  issued fresh for the verification run. Renewal is the next slice by design.
