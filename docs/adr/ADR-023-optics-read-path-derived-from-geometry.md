# ADR-023: Optics read path derived from plate geometry; capture-mode flags deleted

**Status:** Accepted
**Date:** 2026-10-05
**Author:** Nicole Cornell
**Deciders:** 15-well Mk II working group

---

## Context

A Sentri's optics read pass is selected today by per-device string flags in
`host_config.json` — `well_15`, `two_adcs`, `updated4` (plus `motor_test`) —
read into `state_run_assay` and `adc_class` and branched on in ~35 places.
`aq_lib/optics_read_plan.py` also carries hand-written plans (`OPTICS_READ_PLAN`,
`OPTICS_READ_PLAN_2ADC`) chosen by flag.

Phase A (#502–#506) made **Plate Geometry** — resolved from the immutable
`device_identity.json` well count — the single source of truth for layout, and
Slice 5 (#511) made `read_plan(geo)` generate the per-stop channel plan from
that geometry, with a 4-well byte-for-byte parity test. But the flags still
exist alongside geometry, so:

- **Illegal states are representable.** A device can be provisioned 15-well but
  flagged 1-ADC, or flagged `well_15` while its identity says 4 — geometry and
  flags can silently contradict each other.
- **Capture-mode still lives behind a flag** (`updated4`), not derived from the
  plate, and the dual-ADC path is a separate hand-written plan.
- **The well count is still hardcodable** (e.g. the literal `21` reads-per-cycle),
  so a new well count is a code change, not data.

Constraint: the dual-ADC simultaneous (`both`) capture semantics for 15-well are
a **Risk-B** area — a `both` capture reads the ROX and FAM sensors at once while
they sit `sensor_gap` carriage stops apart, so a single `both` at stop *s* spans
two tubes' dyes. The tube↔capture mapping depends on the physical sensor/ADC
wiring and on what analysis expects, and is not yet pinned down. 15-well
hardware is not fielded (Phase C calibration pending).

---

## Decision

**We will generate the entire optics read path from `PlateGeometry` and delete
the `well_15` / `two_adcs` / `updated4` / `motor_test` capture-mode flags, with
the 15-well dual-ADC `both` capture-mode deferred until its Risk-B semantics are
specified.**

Concretely:

- **Capture-mode is a pure function of well count, not a flag:** `well_count == 15
  ⟹ both`; else `phased` (separate `rox`/`fam` blinks). Derived in the optics
  layer from `geo.well_count`; **not** stored on `PlateGeometry` (no consumer
  needs a stored ADC field).
- **`read_plan(geo)` is the single generator.** Layer 1 (geometry→stops, Slice 5)
  stays. Layer 2 (well-count→capture) folds into the plan. The hand-written
  `OPTICS_READ_PLAN_2ADC` and the flag-keyed `if/elif` are deleted.
- **The 2-ADC 4-well path (`updated4` / sn03) is dropped**, not preserved. `sn03`
  becomes a plain 4-well. Re-supporting a 2-ADC 4-well board later requires an
  explicit optics-capability input (see Revisit Conditions).
- **`READS_PER_CYCLE` / completeness math derive from the generated plan** per
  geometry; the hardcoded `21` is removed.
- **Index→physical steps stays in the motor layer**, validated by the Slice 4
  `assert_axis_positions_match(geo, positions)` check. `read_plan` emits logical
  0-origin indices only.

**Phased rollout (this ADR implements the structural half now):**

1. **Now (structural, this ADR):** delete the `updated4` flag and the
   2-ADC-4-well read path; derive the completeness math from geometry; keep
   4-well byte-identical (parity test). 15-well continues to emit the **phased**
   plan it emits today (single-ADC sequential), exactly as `read_plan`'s current
   docstring already defers.
2. **Deferred (Risk-B follow-up):** flip 15-well to dual-ADC `both` capture-mode,
   demote `adc_class` to a dumb `rox`/`fam`/`both` executor, and remove the
   `two_adcs` flag and its buffered `data_both`/`mask_data`/`out_data` machinery.
   This needs the dual-ADC `both` tube↔capture mapping (sensor-gap semantics) and
   what analysis expects — ground truth from the hardware/analysis owners. The
   Variant C crash-safe optics writer (#517 Slice 6) builds on this same buffered
   path and is gated on the same decision.

This decision is **irreversible** in that the flags and the 2-ADC-4-well path are
removed rather than frozen.

---

## Consequences

### Positive
- One source of truth: a device's optics behavior follows its provisioned well
  count; a build/flag mismatch can no longer silently corrupt a run.
- Illegal well-count/ADC combinations become unrepresentable.
- Completeness math can't drift from the actual read pass (derived, not `21`).
- A new well count becomes new geometry *data*, not new branches.

### Negative
- The 2-ADC 4-well capability is gone; re-adding it is a deliberate future change.
- The deferred `both` work leaves `two_adcs` and the dual-ADC buffered path in
  place temporarily (documented, not frozen) until Risk-B is specified.

### Neutral / Tradeoffs
- 15-well stays phased in the interim. No fielded 15-well device exists, so this
  changes nothing observable; the `both` flip lands with its calibration.

---

## Alternatives Considered

### Option A: Preserve the 2-ADC 4-well (`updated4`) path
**Why rejected:** it is the main source of the flag/geometry contradiction and no
fielded device needs it; `sn03` works as a plain 4-well.

### Option B: Store the ADC/capture mode on `PlateGeometry`
**Why rejected:** no consumer needs a stored field; capture-mode derives cleanly
from well count in the optics layer.

### Option C: Keep the `−1` stop origin / `append(0)` pad behind the new plan
**Why rejected:** "no temporary hacks" — nothing in production depends on that
numbering; Slice 5 already removed it.

### Option D: Invent the 15-well `both` capture geometry now
**Why rejected:** Risk-B semantics depend on hardware/analysis ground truth not in
the repo; fabricating them risks a wrong, hard-to-detect mapping.

---

## Revisit Conditions

- When the dual-ADC `both` tube↔capture mapping is specified (hardware + analysis),
  implement the deferred 15-well `both` capture-mode, `adc_class` demotion, and
  `two_adcs` removal — and unblock #517 Slice 6 (Variant C writer).
- If a 2-ADC 4-well board is ever needed again, reintroduce it via an explicit
  optics-capability input, not a resurrected `updated4` flag.

---

## References

- Related ADRs: ADR-001 (hostname-keyed device config)
- Issue: #514 (Phase B); builds on #510 / Slice 5 (#511); gates #517 Slice 6
- Spec: `specs/15-well-mkii-migration.md` (§1a, §19b)
