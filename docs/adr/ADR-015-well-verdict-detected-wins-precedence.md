# ADR-015: Well Verdict precedence is Detected > Inconclusive > Not Detected

**Status:** Proposed
**Date:** 2026-06-19
**Author:** Jack Hu
**Deciders:** Jack Hu

---

## Context

A **Well** produces one **Call** per **Channel** (FAM, ROX). The History detail
page (`aquila_web/static/history_detail.js`) collapses a Well's two Channel Calls
into a single per-Well outcome — the **Well Verdict** — which drives the pill
colour, the `Detected` / `Inconclusive` KPI counts, and the `QC Status`
(Pass / Review) badge.

As built, the verdict precedence is **Inconclusive > Detected > Not Detected**
(`summarizeResults`, ~lines 77–81): if *either* Channel is Inconclusive the whole
Well reads Inconclusive (yellow), even when the other Channel was Detected.
Detected only wins when neither Channel is Inconclusive. Because `QC Status` is
`inconclusiveCount > 0 ? "Review" : "Pass"`, any inconclusive Channel anywhere in
the run forces the run to "Review".

Two things forced a decision:

1. **Operator interpretation.** A Well where the target amplified cleanly on one
   Channel but the other Channel was merely inconclusive currently presents as
   "Inconclusive" overall, which under-states a real detection.
2. **The label collapsed information.** The single-status pill hid which Channel
   was detected vs inconclusive.

This is a change to how a diagnostic result is interpreted and displayed, it
reverses previously-shipped behaviour, and the QC consequence (below) is a real
trade-off — hence an ADR.

Doing nothing keeps inconclusive-wins precedence and the single-status pill.

The live run page (`script.js`) is not in scope — it shows two independently
coloured half-dots and a per-Channel table, with no aggregated verdict.

---

## Decision

**We will make the Well Verdict precedence `Detected > Inconclusive > Not
Detected`, render a dual-channel pill label, and keep QC Status
channel-sensitive (independent of the verdict).**

Concretely:

- **Precedence.** A Well is `Detected` if any Channel is Detected; else
  `Inconclusive` if any Channel is Inconclusive; else `Not Detected`. The verdict
  sets the pill colour.
- **Pill text states both Channels**, grouped by Call in precedence order and
  named by the profile's dye label (FAM/ROX fallback) — e.g.
  `Detected (FAM) Inconclusive (ROX)`, `Not Detected (FAM + ROX)`. Display string
  for the negative Call is `Not Detected` (the canonical `Call` term), not
  "Undetected".
- **KPIs count by verdict, mutually exclusive.** A `Detected(FAM) +
  Inconclusive(ROX)` Well counts toward Detected only, never both.
- **QC Status is channel-sensitive**: `Review` if *any* Channel on any Well has
  an Inconclusive Call (excluding `ROX Unavailable`), independent of the Well
  Verdict. A `Detected(FAM) + Inconclusive(ROX)` Well counts toward the Detected
  KPI but still trips QC Status to **Review** — an inconclusive Channel is never
  passed behind a Detected verdict.
- **`ROX Unavailable`** Calls are excluded from the verdict and the text; the
  verdict comes from FAM alone.

This is **reversible** — it is presentation/aggregation logic in one JS file; no
data-model or stored-`Call` change. The cost of reversing is re-training
operators on result interpretation, not a migration.

See `CONTEXT.md` → **Well Verdict**. Implementation detail in
`specs/analysis/spec_well_verdict_precedence.md`.

---

## Consequences

### Positive
- A Well with a clean detection on one Channel reads as Detected, matching how
  operators interpret the result.
- The pill now names both Channels' Calls, so no per-Channel information is lost
  in aggregation.
- KPI buckets stay mutually exclusive (`detected + inconclusive + not-detected =
  4`), keeping the `/4` denominators meaningful.
- **QC safety is preserved:** an inconclusive Channel still flags Review even
  when the Well Verdict is Detected, so a Detected verdict cannot mask an
  inconclusive result.

### Negative
- Reverses previously-shipped behaviour; anyone trained on inconclusive-wins must
  relearn the rule.
- **Verdict and QC can disagree on the same Well**, which needs explaining: a
  Well shown as Detected (orange pill, Detected KPI) can still drive `QC Status:
  Review`. The pill text (`Detected (FAM) Inconclusive (ROX)`) makes the reason
  visible, but the two indicators are deliberately decoupled.

### Neutral / Tradeoffs
- Data model is untouched — `Call` values (`Detected`, `Not Detected`,
  `Inconclusive`, `ROX Unavailable`) and the `Inconclusive Rate` metric (computed
  per Channel Call, not per Well Verdict) are unaffected.
- The run-level "Result" summary line reflects the new precedence automatically
  but keeps its current format.

---

## Alternatives Considered

### Option A: Keep Inconclusive > Detected precedence
**Why rejected:** Under-states real detections and is the behaviour we are
explicitly changing.

### Option B: Detected-wins for the verdict, with QC also following the verdict (Pass when verdict is Detected)
**Why rejected:** A Detected-overall Well with an inconclusive Channel would read
`Pass`, letting a Detected verdict mask an inconclusive result — unacceptable for
a diagnostic device. QC is therefore evaluated on Channel Calls, not the verdict.

### Option C: Count a mixed Well toward both Detected and Inconclusive KPIs
**Why rejected:** Makes the two `/4` KPIs overlap (sum > 4) and the denominators
ambiguous.

---

## Revisit Conditions

- Operators find verdict/QC disagreement on the same Well confusing in practice →
  revisit how the disagreement is surfaced (e.g. a distinct pill treatment for
  "Detected but QC-flagged") rather than collapsing QC back onto the verdict.
- A symmetric "FAM unavailable" mode is introduced → revisit the ROX-only
  exclusion assumption in the verdict/label logic.
- The live run page gains an aggregated verdict → unify its precedence with this
  decision rather than duplicating it.

---

## References
- Spec: `specs/analysis/spec_well_verdict_precedence.md`
- Related: `specs/analysis/spec_rox_unavailable.md` (`ROX Unavailable` Call), ADR-003 (plain-HTML no-build frontend — why tests are e2e), ADR-008 (PCR analysis post-run pipeline)
- `aquila_web/static/history_detail.js` — `summarizeResults`, pill render, `qcStatus`
- `CONTEXT.md` — **Well Verdict**, **Call**, **Channel**, **Well**
- Issue: #181
