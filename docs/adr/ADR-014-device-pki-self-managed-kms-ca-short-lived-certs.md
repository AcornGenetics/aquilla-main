# ADR-014: Device PKI — self-managed KMS-backed CA issuing short-lived certs

**Status:** Accepted
**Date:** 2026-06-17
**Author:** Nicole Cornell
**Deciders:** Nicole Cornell

---

## Context

ADR-013 made per-device **mTLS** the device-auth mechanism for ingest and called
PKI "a hard requirement," but deliberately left the PKI itself unspecified: who
runs the Certificate Authority, what the cert identity is, how long certs live,
how devices enroll and renew, how revocation works, and where the CA private key
lives. The `sentri-analytics-system-design.md` only states that the **truststore
(signing CA public cert) lives in S3** and is consumed by API Gateway HTTP API
mTLS validation. This ADR fills that gap.

Relevant facts and constraints at decision time:

- The fleet is **<100 physical Raspberry Pi Sentris**, **one prod fleet** (no
  physical dev fleet), and each Pi is **online daily**.
- **API Gateway HTTP API mTLS does not natively perform CRL/OCSP revocation
  checking.** The truststore is just a CA bundle; per-device revocation must be
  solved out-of-band (custom deny-list, or CA/truststore rotation).
- **Cost sensitivity:** ACM Private CA is **~$400/mo** (general-purpose) or
  **~$50/mo** (short-lived-certificate mode) **per CA**, which dwarfs the
  architecture's other line items at this scale (design §9).
- **Effectively greenfield:** only one Pi currently syncs and its data is
  disposable, so the PKI model can be chosen freely without a migration of live
  credentials.

## Decision

1. **Cert identity = Device ID.** The certificate Subject CN is the Pi hardware
   serial (Device ID). The platform derives device identity from the cert; the
   request body's `device_id` is a **cross-check only** and a mismatch is
   rejected. This binds the transport identity to the data-model identity. See
   `CONTEXT.md` → Device Certificate.
2. **Self-managed CA, private key in AWS KMS — not ACM Private CA.** The CA is a
   self-signed root whose private key is a non-extractable KMS asymmetric key;
   CSRs are signed via the KMS `Sign` API. The S3 truststore is this CA's public
   cert. Cost is **~$1/mo** instead of ~$400/mo, with HSM-grade key custody.
3. **Short-lived certs (≤7 days), auto-renewed.** Revocation is handled by
   **non-renewal** — a compromised or stolen Pi self-expires within the cert
   lifetime — which sidesteps the API Gateway mTLS revocation gap entirely.
4. **On-device keygen; brokered signing.** Each Pi generates its own keypair and
   CSR (`CN=Device ID`); the **private key never leaves the device**. Initial
   **enrollment is operator-authenticated** (`scripts/deploy/deployment2.sh`).
   **Renewal is automated and authenticated by the device's current valid cert**
   (mTLS) against a renewal endpoint; a renewal daemon on the Pi swaps certs
   before expiry. A Pi offline longer than its cert lifetime drops back to manual
   re-enrollment (rare — the fleet is online daily).
5. **One CA for the single prod fleet.** No dev-fleet CA. If the dev platform
   environment needs ingest traffic, it uses simulation mode (ADR-007) or
   throwaway certs, not physical hardware.

## Consequences

### Positive
- Eliminates the ~$400/mo ACM PCA cost; the CA is ~$1/mo.
- Neutralizes revocation — the hardest unsolved operational item on API Gateway
  mTLS (design §7) — via short cert lifetime instead of CRL/OCSP infrastructure.
- Device private keys never traverse the network or a provisioning host.
- A single identity (Device ID) spans transport (cert CN) and data model.

### Negative
- Adds a **renewal daemon on every Pi** (device-side, this repo) and a
  **renewal/signing endpoint** (platform-side, sentri-analytics). This is the
  price of revocation-by-non-renewal.
- **CA key custody becomes our responsibility** (mitigated by keeping the key in
  KMS, non-extractable).
- A Pi offline beyond its cert lifetime cannot self-renew and needs operator
  re-enrollment.
- Per-cert issuance volume rises with renewal frequency (cost remains trivial).

### Neutral / Tradeoffs
- Short-lived certs depend on the **daily-online** assumption; acceptable for
  this fleet. If that assumption breaks, see Revisit Conditions.

## Alternatives Considered

### ACM Private CA, general-purpose mode
**Why rejected:** ~$400/mo per CA is unjustified at <100 devices; the managed
convenience is not worth the cost when a KMS-backed self-managed CA achieves the
same truststore-in-S3 outcome.

### ACM Private CA, short-lived-certificate mode (~$50/mo)
**Why rejected:** Still pays for a managed CA where a KMS-backed self-managed CA
delivers the same short-lived posture at ~$1/mo.

### Long-lived certs (1–3 yr) + revocation deny-list
**Why rejected:** Requires building revocation infrastructure that API Gateway
mTLS lacks natively (no CRL/OCSP), e.g. an app-side deny-list checked per
request. Short-lived certs avoid that work. Retained as the **fallback** if
auto-renewal proves operationally fragile.

### Central keygen + push to devices
**Why rejected:** The private key would traverse a provisioning host/network and
exist in bulk at provisioning time, weakening the per-device identity guarantee
that justified moving off the shared key.

### CA owned inside aquila-main or sentri-analytics application code
**Why rejected:** Splitting issuance from the S3 truststore invites a
CA/truststore mismatch that fails handshakes fleet-wide. A standalone CA (KMS key
+ S3 truststore) consumed by both repos keeps trust single-owned.

## Revisit Conditions

- Auto-renewal proves fragile (Pis frequently offline past cert lifetime) →
  switch to long-lived certs + a deny-list revocation path, or lengthen the cert
  lifetime.
- Fleet grows enough that self-managed CA operations become a burden →
  reconsider ACM PCA short-lived mode.
- A compliance trigger requires a managed/audited CA → ACM PCA or external PKI.

## References

- ADR-013 (per-device mTLS device auth — this ADR specifies its PKI)
- ADR-007 (simulation mode — source of dev-platform test traffic)
- `sentri-analytics-system-design.md` §3, §7 (truststore in S3; revocation as an
  open item)
- `CONTEXT.md` — Device Certificate, Device ID
- `aquila_web/sync.py`, `scripts/deploy/deployment2.sh`,
  `scripts/deploy/fleet-update.sh` — device-side enrollment/renewal
