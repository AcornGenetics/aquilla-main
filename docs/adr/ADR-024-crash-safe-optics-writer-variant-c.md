# ADR-024: Crash-safe optics writer — Variant C (raw safety log + mask on any stop)

**Status:** Accepted
**Date:** 2026-10-05
**Author:** Nicole Cornell
**Deciders:** 15-well Mk II working group

---

## Context

The dual-ADC `both` optics path buffers every raw sample in RAM (`self.data_both`)
for the whole run and only masks + writes the optics file at `quit`
(`out_data()` → `mask_data()`, `aq_lib/adc_class.py`; sole caller is the executor
`quit` branch, `state_run_assay.py`). Two problems:

- **No data on an abnormal stop.** If a run is cancelled or crashes before
  `quit`, `out_data()` never runs and the entire capture is lost — even though
  cancel is a common, supported flow.
- **Whole-run RAM.** The raw buffer grows with the run; for 15 wells × many
  cycles that is a large, unbounded footprint.

A colleague's 2026-09-30 source offered a per-pass incremental writer, but it was
**rejected** (#517 §27): it keeps the whole raw buffer anyway (no RAM win) and
restructures the `scan_num`/`rox_index` read path that is our 15-well work.

Constraints that any replacement must honor:
- The optics output file is a **frozen hashed contract** (ADR-0007 /
  acorn-analytics#45): whole-file hash + row count, `SAMPLES_PER_BLINK`.
- `capture_blink` is **shared** with `scripts/tools/melt_curve.py`, which must
  not start emitting a raw safety log.
- The `-123` repair's deepest look-back is **one pass**
  (`i - scan_num*4*blink_num`); the half-period repair looks back one sample.

---

## Decision

**We will adopt Variant C: stream raw samples to a separate raw safety log during
the run, and mask + write the optics file on ANY stop (complete / cancel /
crash), reading the raw log back one pass at a time so RAM stays bounded to ~2
passes.**

Concretely:

- **During a run:** append raw `both` samples to a **separate raw safety log**
  file, gated on run context so the shared `capture_blink` path used by
  `melt_curve.py` is unaffected (melt_curve never writes the raw log).
- **On ANY stop:** mask + write the optics file. Masking **reads the raw log back
  one pass at a time** (keeping the previous pass for the `-123` fallback
  look-back), so the working set is **~2 passes**, not the whole run. Wire this
  into the executor `quit` branch AND the cancel/crash paths
  (`clean_up`/`finally`) so an aborted run still yields its captured data.
- **Byte-identical gate:** the pass-by-pass ("ring") mask must produce
  **byte-identical** output to the current all-at-once ("batch") mask. This is a
  hard unit test (`ring-mask == batch-mask`) and is why a 2-pass window suffices:
  the deepest dependency is one pass back.
- **Recovery tool:** a standalone re-mask tool reconstructs the optics file from
  a leftover raw safety log (e.g. after a hard crash that skipped even the stop
  handler).
- **Uploader isolation:** the raw safety log is a **separate file the outbox /
  uploader never scans** — only the masked optics file is synced.

This builds on the Slice 7 width parameterization (`w = blink_num`): rows per
capture = `6*w`, so the pass size the window tracks is `scan_num * 6*w`.

Irreversible in that the whole-run buffer-and-write-at-quit model is replaced.

---

## Consequences

### Positive
- A cancelled or crashed run still produces its captured optics data.
- RAM bounded to ~2 passes regardless of run length.
- The frozen optics contract is preserved by construction (byte-identical gate).

### Negative
- A new on-device artifact (the raw safety log) with its own lifecycle (write,
  consume on stop, clean up, never upload) and a recovery tool to maintain.
- Masking logic must be expressed in a windowed form that provably equals the
  batch form — more structure than the current single pass over the buffer.

### Neutral / Tradeoffs
- Disk I/O during the run (append to raw log) instead of pure RAM buffering.

---

## Alternatives Considered

### Option A: Colleague's per-pass incremental writer
**Why rejected:** keeps the whole raw buffer (no RAM win) and restructures the
15-well `scan_num`/`rox_index` read path that is our active work.

### Option B: Keep buffering, add a try/finally that calls `out_data` on cancel
**Why rejected:** solves the cancel-data-loss half but not the whole-run RAM, and
still loses data on a hard crash (no raw log to recover from).

---

## Revisit Conditions

- If the optics file format changes materially (e.g. the deferred 15-well tube-id
  / samples-per-blink work lands), re-verify the byte-identical gate against the
  new golden fixture.
- If a future capture mode's repair look-back exceeds one pass, the 2-pass window
  must grow accordingly.

---

## References

- Related ADRs: ADR-023 (optics read path derived from geometry), ADR-0007 /
  acorn-analytics#45 (optics-file hash contract)
- Issue: #517 Slice 6 (Variant C); spec `specs/15-well-mkii-migration.md` §7
  (RISK C), §21a, §27
