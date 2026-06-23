# ADR-015: Ingest moves to `acorn-analytics` as a serverless Lambda pipeline

**Status:** Accepted — amends ADR-013 (supersedes its "ingest served by the ASG application" sub-decision; ADR-013's mTLS/cert-CN decisions remain in force)
**Date:** 2026-06-18
**Author:** Nicole Cornell
**Deciders:** Nicole Cornell

---

## Context

ADR-013 retired this repo's SAM ingest stack and moved ingest ownership to "the
sentri-analytics platform," where ingest would be **served by the ASG
application** — the same operated platform that served the dashboard. Its stated
justification was convergence: *"Ingest and analytics converge on one operated
platform (ASG app), removing the SAM Lambda/SQS/S3 pipeline."*

The system has since been re-architected into a six-repository split (see
`sentri-analytics/specs/six-repo-architecture.md`). Under that split the dashboard
(`acorn-app`) and the ingest+analytics tier (`acorn-analytics`) are **separate
repos, stacks, and blast radii** — the convergence premise that justified
ASG-served ingest is deliberately removed. The ASG belongs to the dashboard; it
is not where ingest should run.

Facts at decision time:
- Ingest is **spiky 15-minute batch POSTs from <100 devices** — the canonical
  scale-to-zero serverless workload. An ASG sized for ingest would idle ~99% of
  the time.
- The plan requires a **no-data-loss / buffer-and-retry** ingest path; SQS + an
  S3 raw archive provide durable buffering and a replayable source of truth for
  free, which an ASG app would have to reimplement.
- The security model requires the **public ingest edge and the user dashboard to
  be separate blast radii**; sharing an ASG re-couples them.

Doing nothing would leave two accepted-but-contradictory positions on ingest
hosting (ADR-013's ASG-served ingest vs. the six-repo spec's Lambda pipeline).

---

## Decision

**We will host ingest in `acorn-analytics` as a serverless pipeline:
`API Gateway → ingest Lambda → SQS → archiver Lambda → S3 (raw archive) →
loader/ETL Lambda → analytics warehouse`.**

Concretely:
- **Three Lambdas:** *ingest* (validate, derive `device_id` from the mTLS cert
  CN, enqueue to SQS), *archiver* (SQS consumer → S3 raw archive), *loader/ETL*
  (S3 → star-schema warehouse).
- **`acorn-analytics` owns this code and its deploy**; it deploys onto shared
  substrate (API Gateway, SQS, S3) provisioned by `acorn-infra`.
- **ADR-013's transport-auth decisions are unchanged:** mTLS terminates at API
  Gateway against the S3 truststore, and device identity is derived from the
  cert CN, not the request body.
- **The CA cloud side moves to `acorn-ca`** (the standalone KMS-backed CA that
  ADR-014 already called for); this repo keeps only the device-side
  enrollment/renewal daemons.
- This is the same direction ADR-013 set (ingest leaves this repo); it changes
  only *where* ingest runs in the cloud (Lambda pipeline, not ASG app).

Reversible during migration (repoint the fleet endpoint); the hosting shape
itself is a cloud-side concern with no device impact.

---

## Consequences

### Positive
- Scale-to-zero ingest matched to a spiky, low-volume batch workload; no idle ASG.
- Durable buffering (SQS) and a replayable raw archive (S3) satisfy the
  no-data-loss requirement without custom code.
- Ingest and dashboard stay separate blast radii, as the security model requires.
- Removes the API-GW → VPC Link → ALB → ASG chain ADR-013 implied, simplifying
  the substrate `acorn-infra` must provision.

### Negative
- Re-introduces the Lambda/SQS/S3 operational surface ADR-013 had folded into the
  ASG app — three functions to deploy and monitor instead of one app.
- Ingest contract changes now coordinate across `aquilla-main` ↔ `acorn-analytics`
  (unchanged from ADR-013's cross-repo coordination cost).

### Neutral / Tradeoffs
- The `run_complete` payload contract and device-side sync code are unaffected —
  this is purely a cloud-side hosting decision.

---

## Alternatives Considered

### Keep ingest on the ASG application (ADR-013 as written)
**Why rejected:** the six-repo split removes the convergence premise; an ASG
sized for spiky low-volume ingest idles ~99% of the time and re-couples the
ingest edge with the dashboard blast radius.

### A single ingest Lambda writing straight to the warehouse (no SQS/S3)
**Why rejected:** drops the durable buffer and replayable raw archive that the
no-data-loss requirement depends on.

---

## Revisit Conditions

- Fleet/volume grows enough that a streaming path (Kinesis) or always-on compute
  beats per-invocation Lambda — revisit the pipeline shape (cf. ADR-009's 500+
  device threshold).
- If ingest and analytics ever need to re-converge onto one operated platform,
  re-open the hosting decision.

---

## References

- Amends: ADR-013 (per-device mTLS; ingest leaves this repo) — supersedes only its
  ASG-ingest hosting sub-decision
- Related: ADR-014 (KMS-backed standalone CA — its cloud side becomes `acorn-ca`),
  ADR-009 (original Lambda ingest; superseded by ADR-013)
- Spec: `sentri-analytics/specs/six-repo-architecture.md` (Repo 3 — `acorn-analytics`)
