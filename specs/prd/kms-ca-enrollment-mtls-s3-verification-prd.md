# PRD: KMS-backed CA — password-gated device enrollment in deployment + mTLS→S3 verification slice

> **Tracking issue:** [#176](https://github.com/AcornGenetics/aquilla-main/issues/176)
> **Revision 1 — 2026-06-17**
>
> **Tracer-bullet vertical slice** carved from `specs/Data-pipline/device-edge-mtls-migration-prd.md`.
> Anchored by **ADR-014** (device PKI: self-managed KMS-backed CA, on-device keygen, operator-authenticated enrollment) and **ADR-013** (device auth → mTLS; truststore in S3, consumed by API Gateway mTLS). Glossary in `CONTEXT.md` (Sentri, Device ID, Device Certificate, Ingest Endpoint, Sync, Event).
>
> **Goal of this slice:** prove the whole chain end-to-end on real infrastructure — *KMS-backed CA exists → a Sentri enrolls during deployment (gated by an operator password) → the Sentri presents its Device Certificate to an mTLS gateway → the Event lands in S3.* It is the smallest runnable proof that ADR-014's PKI works before the broader renewal/Aurora/decommission work is built.

## Problem Statement

I have ADR-014 (a self-managed, KMS-backed CA issuing per-device Device Certificates) on paper, but nothing that proves it works. Today a Sentri authenticates to the Ingest Endpoint with a shared Fleet API Key (`x-api-key`) that isn't even enforced, and my deployment script (`deployment2.sh`) just prompts for that shared key and writes it to `device.env`. There is:

- no Certificate Authority actually standing (no KMS key, no root cert, no truststore in S3),
- no way for a Sentri to *get* a certificate when I deploy it — and no gate stopping just anyone from minting one,
- no demonstration that a certificate, once on a device, actually authenticates a real upload all the way into S3.

Until I can run that chain from nothing and watch an Event land in the bucket because of the certificate, I can't trust the design or build the rest of the migration on top of it.

## Solution

From my (the operator's) and the fleet's perspective:

- **A CA exists, once, with one command.** A one-time bootstrap creates a non-extractable KMS asymmetric key, builds the self-signed root certificate by signing it through the KMS `Sign` API, and publishes the root (the **truststore**) to the S3 location the gateway's mTLS validation reads. The CA private key never exists outside the KMS HSM.
- **Deploying a Sentri gets it a certificate.** When I run `deployment2.sh`, the Sentri generates its own keypair on-device and a CSR with `CN=<Device ID>`, I am prompted for an **enrollment password**, and the signing path issues a Device Certificate only if that password is valid. The certificate and key land on the Pi `chmod 600`; the device's private key never leaves the Pi and the Pi never holds a credential that could mint *other* certificates.
- **The shared Fleet API Key is gone.** Deployment stops prompting for / writing `AQ_SYNC_API_KEY`; the Sentri presents its Device Certificate on Sync instead of an `x-api-key` header.
- **I can verify it works.** A test/verification script run from the device presents the Device Certificate to the **mTLS Ingest Endpoint** and POSTs a sample Event; I can then see that exact Event archived as an object in the raw-events S3 bucket. A bad/absent/wrong-CA certificate fails the handshake and nothing lands. That is the proof.

## User Stories

1. As an operator, I want a one-command CA bootstrap, so that I can stand up the Certificate Authority without hand-assembling keys.
2. As a security-conscious operator, I want the CA private key created as a non-extractable KMS asymmetric key, so that the root signing key can never be exported or leaked.
3. As an operator, I want the self-signed root certificate produced by signing through the KMS `Sign` API, so that the root is bound to the KMS key without the private key ever leaving the HSM.
4. As an operator, I want the root certificate (truststore) published to the S3 location the gateway reads, so that API Gateway mTLS can validate device certificates against it.
5. As an operator, I want the bootstrap to be idempotent / safe to re-run, so that re-running it does not silently create a second CA or clobber the live truststore.
6. As a Sentri, I want to generate my own keypair on-device during deployment, so that my private key never leaves the Pi.
7. As a Sentri, I want to build a CSR with `CN=<Device ID>`, so that my transport identity equals my data-model identity (the Pi hardware serial).
8. As an operator, I want `deployment2.sh` to prompt me for an enrollment password (masked input), so that obtaining a certificate requires my authorization at provisioning time.
9. As the signing path, I want to verify the enrollment password before signing a CSR, so that an unauthenticated caller cannot mint a Device Certificate.
10. As the signing path, I want to sign the device CSR through the KMS `Sign` API, so that issuance uses the same HSM-held CA key as the root.
11. As the signing path, I want to set the certificate's `CN` from the CSR's `CN` (the Device ID) and a short validity window, so that issued certificates carry the right identity and posture.
12. As a Sentri, I want my certificate and private key written `chmod 600`, so that they are not world-readable on the device.
13. As a Sentri, I want the certificate and key paths recorded in `device.env`, so that the Sync client and verification script can find them.
14. As an operator, I want enrollment to fail loudly (non-zero exit, clear message) on a wrong password or signing error, so that a deployment never silently completes without a valid certificate.
15. As an operator, I want `deployment2.sh` to stop prompting for and writing `AQ_SYNC_API_KEY`, so that the retired shared-key model is removed from new deployments.
16. As a Sentri, I want to present my Device Certificate (client cert + key) on the Sync POST instead of an `x-api-key` header, so that I authenticate by mTLS.
17. As an operator, I want the Ingest Endpoint gateway configured for mTLS with the S3 truststore, so that only certificates signed by my CA complete the handshake.
18. As an operator, I want a verification script I can run from the device, so that I can confirm the certificate authenticates a real upload end-to-end.
19. As an operator, I want the verification script to POST a sample Event over mTLS and then confirm the object exists in the raw-events S3 bucket, so that I have proof the chain works into storage, not just at the handshake.
20. As an operator, I want the verification to fail when no certificate, an expired certificate, or a wrong-CA certificate is presented, so that I know the gateway is actually enforcing mTLS and not accepting anything.
21. As a developer, I want the CSR-subject construction (`CN=Device ID`) extracted as pure logic, so that it is unit-testable without hardware.
22. As a developer, I want the signing logic tested against a stubbed KMS, so that "valid password → signs; bad password → refuses" is verified without real AWS calls.
23. As a developer, I want the device Sync auth change covered by the existing Sync test seam, so that "certificate sent, no `x-api-key`" is verified automatically.
24. As a developer, I want the gateway mTLS + truststore configuration asserted against the infra template, so that a redeploy can't silently drop mTLS enforcement.
25. As an operator, I want the existing raw-events S3 bucket and archiver path reused for verification, so that the slice proves the real ingest-to-storage route rather than a throwaway one.

## Implementation Decisions

### CA bootstrap (self-managed, KMS-backed — ADR-014)
- A one-time bootstrap (a `scripts/` utility) creates a **KMS asymmetric key** (usage `SIGN_VERIFY`, e.g. RSA/ECC), reads its **public key**, and assembles a **self-signed root certificate** whose signature is produced via the KMS `Sign` API (the private key is non-extractable and never leaves the HSM).
- The root certificate (the **truststore** / CA public cert) is uploaded to the **S3 location the gateway's mTLS validation reads**. The KMS private key is the single root of trust; no raw CA key file ever exists on disk.
- Bootstrap is **idempotent / guarded**: re-running detects an existing CA key + truststore and refuses to silently replace them.

### Certificate signing path (operator-authenticated — "enrollment password")
- A signing function takes a **CSR + an enrollment token/password**, **verifies the password first**, and only then signs the CSR via KMS `Sign`, returning a Device Certificate with `CN` carried from the CSR and a short validity window.
- A wrong/absent password is rejected without signing. (Where the signing path is hosted — small Lambda vs. local invocation during this slice — is an implementation detail; the contract is *password-gated, KMS-signed issuance*. Auto-renewal and a cert-authenticated renewal endpoint are **out of scope** here — see Out of Scope.)

### Device enrollment in `deployment2.sh`
- During deployment the Sentri **generates its own keypair** and a **CSR with `CN=<Device ID>`** (Device ID = the Pi hardware serial per `CONTEXT.md`; the script already establishes a `DEVICE_ID`).
- `deployment2.sh` prompts for the **enrollment password using its existing masked-prompt helper** (`prompt_if_unset … true` / `read -rsp`), submits CSR + password to the signing path, and on success writes the **certificate and key `chmod 600`** and records their paths in `device.env`.
- The script **stops prompting for and writing `AQ_SYNC_API_KEY`**; the Fleet API Key is removed from new deployments. Enrollment failure (bad password / signing error) **exits non-zero with a clear message** — no silent completion.
- Pure logic (CSR subject construction = `CN=Device ID`) is extracted into Python so it is unit-testable; the on-device keygen/install steps are host-dependent.

### Device Sync auth (`aquila_web/sync.py`)
- The Sync client **drops the `x-api-key` header** and presents the **client certificate + key** on the POST (`cert=(client_cert, client_key)` style). Certificate/key paths come from `device.env`. The Event payload shape is **unchanged** (still keyed on `device_id`).

### mTLS gateway → S3 (reuse existing SAM ingest path)
- Enable **mTLS on the existing `AWS::Serverless::HttpApi` Ingest Endpoint** (`infra/template.yaml`) with the **S3 truststore** from bootstrap; disable the default execute-api endpoint so only the mTLS-validated path is reachable. The existing **`S3ArchiverFunction` → `RawEventsBucket` (`sentri-raw-events-${AccountId}`)** route is **reused** as the ingest-to-storage path under test.
- This is the production-shaped verification path (API Gateway mTLS per ADR-013), not IAM Roles Anywhere.

### Verification script
- A device-side script loads the Device Certificate from `device.env`, **POSTs a sample Event over mTLS** to the Ingest Endpoint, then **confirms the resulting object exists in `RawEventsBucket`**. Negative cases (no cert / expired / wrong-CA) must fail the handshake and land nothing.

## Cloud Prerequisites

This slice documents a chain whose **cloud half must exist for the acceptance test to run**. Built against **this repo's existing SAM stack** (`infra/template.yaml`) — not the full Sentri Analytics Platform edge (see Out of Scope) — in this order:

> **Ownership — here vs. the platform.** In the **production end-state**, these are **Sentri Analytics Platform (`Acorn/sentri-analytics`) deliverables**: the platform owns ingest, so the real mTLS gateway, truststore, and signing/renewal endpoint live there (see the migration PRD's Out of Scope). The **CA itself is standalone** — a KMS key + S3 truststore consumed by *both* repos, deliberately **not** owned inside either app's code (ADR-014 rejected "CA owned inside aquila-main or sentri-analytics application code" to keep trust single-owned).
>
> This slice builds a **proof-harness version here, transiently**, because its purpose is to prove ADR-014 works *before* the platform edge exists. To avoid rework, create the **KMS key + S3 truststore as standalone AWS resources** (so the same CA carries over to the platform); only the **bootstrap script and the proof signing endpoint live transiently in `aquila-main`** and are retired when the platform edge ships and the old SAM ingest stack is decommissioned (migration PRD cutover).

### 1. CA / PKI — the root of trust
- A **KMS asymmetric key** (usage `SIGN_VERIFY`, non-extractable) — this *is* the CA private key.
- A **one-time CA bootstrap**: read the KMS public key, assemble the self-signed root by calling `kms:Sign`, and **upload the root (truststore) to S3**. Enable **bucket versioning** — API Gateway mTLS pins a truststore object *version*.
- **IAM**: a role permitted to call `kms:Sign` on that key, granted only to the signing path (§2).

### 2. Enrollment / signing endpoint — what `deployment2.sh` calls
- A **hosted function** (Lambda + an HTTPS front: API Gateway or Lambda Function URL) that accepts a CSR + enrollment password, **verifies the password**, calls `kms:Sign`, and returns the signed Device Certificate.
- The **enrollment secret** stored in Secrets Manager / SSM Parameter Store.
- **Chicken-and-egg constraint:** this endpoint **cannot** be mTLS-protected — the device has no certificate yet — which is precisely why it is **password-gated**. It is the one cloud surface authenticated by the operator password rather than by a certificate.

### 3. mTLS Ingest Endpoint — where the certificate is proven
API Gateway mTLS is **more than a flag**: it requires a custom domain. On the existing `AWS::Serverless::HttpApi`:
- a **custom domain name**,
- an **ACM (or imported) server certificate** for that domain,
- a **Route 53 / DNS** record,
- `mutualTlsAuthentication` pointing at the **S3 truststore URI + version** from §1,
- `disableExecuteApiEndpoint = true` so only the mTLS path is reachable.
- **No revocation:** API Gateway mTLS performs no CRL/OCSP checking — which is *why* ADR-014 relies on short-lived certs + revocation-by-non-renewal, not on the gateway revoking.

### 4. Data sink — already exists, reused
- The existing **`S3ArchiverFunction` → `RawEventsBucket` (`sentri-raw-events-${AccountId}`)** path. **Nothing new** — landing an Event here is the proof.

> **Minimum to make this slice verifiable:** §1, §2, and the custom-domain/ACM/truststore additions in §3, against this repo's SAM stack. Everything else (the full platform edge) is Out of Scope.

## Testing Decisions

Good tests assert **external behavior at the highest available seam** — what the device puts on the wire, what the signing path returns for good vs. bad input, and what infra resources exist — not internal call order. Mock the network boundary (`requests.post`) and AWS boundaries (botocore `Stubber` / `tmp_path`) rather than reaching for real services in unit tests.

- **Device Sync auth — existing seam (`POST /sync/flush` → `aquila_web.sync`).** Prior art: `tests/unit/test_background_sync.py` (monkeypatches `aquila_web.sync.requests.post`, captures call kwargs). Replace the `x-api-key` assertion with: the client-certificate tuple is passed and **no** `x-api-key` header is present. Keep "no endpoint → synced 0" and "network error swallowed, events stay pending" green.
- **CSR subject construction.** Pure-logic unit test (`unit_tests/`): given a Device ID, the CSR subject is `CN=<Device ID>`. Prior art: `unit_tests/test_optics_history.py`, `tests/unit/test_device_id.py`.
- **CA bootstrap + signing.** Unit test the cert-assembly + signing logic against a **stubbed KMS** (botocore `Stubber`): root cert is signed via KMS `Sign`; a device CSR with a valid enrollment password is signed and carries `CN` from the CSR; a **wrong/absent password is refused without a `Sign` call**; re-running bootstrap against an existing CA refuses to clobber. Prior art for handler/infra-style tests: `tests/infra/` (`test_s3_archiver.py`, `test_ingest_handler.py`).
- **Gateway mTLS + truststore.** Light infra assertion: parse `infra/template.yaml` and assert the HttpApi has mTLS enabled, references the S3 truststore, disables the default execute-api endpoint, and that the `S3ArchiverFunction` → `RawEventsBucket` route is intact. Prior art: `tests/infra/conftest.py` template-parsing pattern.
- **Enrollment / on-device keygen.** Host-dependent (keygen, install, `deployment2.sh`) — mark `@pytest.mark.hardware` with a documented "why not CI" note per the repo testing rules; cover the extractable pure logic (CSR subject) above.
- **End-to-end acceptance (the real proof).** After `sam deploy` + bootstrap: from a Sentri with an enrolled certificate, the verification script POSTs a sample Event over mTLS and the matching object appears in `RawEventsBucket`; presenting no / expired / wrong-CA certificate fails the handshake and lands nothing.

## Out of Scope

Owned by the broader migration PRD (`specs/Data-pipline/device-edge-mtls-migration-prd.md`) or the **Sentri Analytics Platform** (`Acorn/sentri-analytics`), **not** this slice:

- **Automatic certificate renewal**, the cert-authenticated renewal endpoint (`POST /sync/cert/renew`), the on-device renewal daemon, atomic mid-renewal swap, and the offline-too-long re-enrollment path. This slice is **enroll-once + verify**; renewal is the next slice.
- Revocation-by-non-renewal mechanics beyond the short validity window itself.
- The full production **Sentri Analytics Platform edge** (VPC Link, internal ALB, ASG, the Node `/ingest` app, regional custom domain, rate-limit store). This slice reuses the existing SAM `HttpApi` + `S3ArchiverFunction` + `RawEventsBucket` purely to prove the certificate chain.
- **Aurora connectivity** (peering, return route, `DBSecurityGroup` ingress, `sentri_readonly` role) — independent track in the broader PRD.
- **Decommissioning** the old SAM ingest stack and the **big-bang fleet cutover**.
- Backfill-tool auth change; any Event payload schema change (this slice is auth-only); any dev-fleet certificate isolation (one prod fleet, one CA).

## Further Notes

- This is intentionally the **smallest end-to-end runnable proof** of ADR-014: CA → enrollment (password-gated) → certificate on device → mTLS → S3. Everything in scope can be built and unit-tested now against mocks; the **acceptance test** needs the bootstrapped CA, the mTLS-enabled gateway, and one enrolled Sentri.
- The short-validity posture is acceptable here because the slice doesn't yet auto-renew — certificates are issued fresh for the verification run. Renewal is deferred to the next slice by design.
- The KMS-backed CA eliminates the ~$400/mo ACM Private CA cost while keeping HSM-grade key custody (ADR-014); long-lived certs + a deny-list remain the documented fallback if the eventual auto-renewal proves fragile.
- Device ID note: `deployment2.sh` currently derives `DEVICE_ID` from the hostname; `CONTEXT.md`/ADR-014 define Device ID as the Pi hardware serial. Reconciling the two is a small clarification to settle during implementation (the CSR `CN` must equal whatever the platform treats as the Device ID).
