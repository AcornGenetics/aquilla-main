# Spec: Well Verdict precedence + dual-channel pill label

## Summary

Change how the **History detail** page aggregates a Well's two Channel Calls into a single per-Well result, and how that result is labelled.

Two changes:

1. **Precedence reversal.** The Well Verdict precedence becomes **Detected > Inconclusive > Not Detected** (today it is Inconclusive > Detected > Not Detected). A Well is now `Detected` if *any* Channel is Detected, even when the other Channel is Inconclusive.
2. **Dual-channel pill text.** Each Well's pill always names *both* Channels and their individual Calls — e.g. `Detected (FAM) Inconclusive (ROX)` — instead of collapsing to a single status word.

Scope is the **History detail page only** (`aquila_web/static/history_detail.js`). The live run page (`script.js`) is **unchanged** — it already shows two independently-coloured half-dots and a per-Channel table.

See `CONTEXT.md` → **Well Verdict** for the canonical term.

---

## Behaviour

### Well Verdict (precedence)

For each Well, from its FAM Call (`data["1"][tube]`) and ROX Call (`data["2"][tube]`):

| FAM | ROX | Verdict (color) |
|---|---|---|
| Detected | Detected | **Detected** |
| Detected | Inconclusive | **Detected** |
| Detected | Not Detected | **Detected** |
| Inconclusive | Inconclusive | **Inconclusive** |
| Inconclusive | Not Detected | **Inconclusive** |
| Not Detected | Not Detected | **Not Detected** |

Rule: `Detected` if any Channel is Detected; else `Inconclusive` if any Channel is Inconclusive; else `Not Detected`. The verdict sets the pill color class (`run-detail-pill--detected` / `--inconclusive` / `--not-detected`) — these CSS classes already exist.

### Pill text (dual-channel label)

The pill always states something for **both** Channels. Format rules:

- Group Channels by their Call, **ordered by precedence**: Detected group first, then Inconclusive, then Not Detected.
- Within a group, list Channels in **FAM, then ROX** order, joined with ` + `.
- Render each group as `Status (label[ + label])`. Join groups with a single space.
- Channel display name = the profile's **dye label** (`labels.fam` / `labels.rox`), falling back to literal `FAM` / `ROX` when unset. (Matches the results-table headers and the current detected-label behaviour.)
- The not-detected display string is **`Not Detected`** (matches the `Call` glossary term — *not* "Undetected").

Examples (profile with no custom labels):

| FAM | ROX | Pill text |
|---|---|---|
| Detected | Detected | `Detected (FAM + ROX)` |
| Detected | Inconclusive | `Detected (FAM) Inconclusive (ROX)` |
| Not Detected | Inconclusive | `Inconclusive (ROX) Not Detected (FAM)` |
| Detected | Not Detected | `Detected (FAM) Not Detected (ROX)` |
| Not Detected | Not Detected | `Not Detected (FAM + ROX)` |

Example with `labels.fam = "Target"`, `labels.rox = "Control"`:
`Detected (Target) Inconclusive (Control)`

The pill is still prefixed with the tube name, e.g. `Tube 1: Detected (Target) Inconclusive (Control)`.

### ROX Unavailable

When a Channel's Call is `"ROX Unavailable"` (the `rox_unavailable` profile mode, see `spec_rox_unavailable.md`):

- Exclude that Channel from **both** the verdict and the pill text.
- The Well Verdict comes from the remaining Channel (FAM) alone.
- The pill shows FAM only — e.g. `Tube 1: Detected (Target)`.

| FAM | ROX | Verdict | Pill text |
|---|---|---|---|
| Detected | ROX Unavailable | Detected | `Detected (Target)` |
| Not Detected | ROX Unavailable | Not Detected | `Not Detected (Target)` |
| Inconclusive | ROX Unavailable | Inconclusive | `Inconclusive (Target)` |

### KPIs and QC Status

- **Detected / Inconclusive KPIs** count Wells by **Well Verdict**, mutually exclusive — each Well lands in exactly one bucket. A `Detected (FAM) + Inconclusive (ROX)` Well counts **only** toward Detected, never both. `detected + inconclusive + not-detected = 4` always.
- **QC Status is channel-sensitive** (decoupled from the verdict): `Review` if *any* Channel on *any* Well has an `Inconclusive` Call (excluding `ROX Unavailable`), else `Pass`. Consequence: a `Detected(FAM) + Inconclusive(ROX)` Well counts toward the **Detected** KPI but still flips QC Status to **Review** — an inconclusive Channel is never silently passed behind a Detected verdict. (See ADR-015.)

---

## Code changes

All in `aquila_web/static/history_detail.js`.

### `summarizeResults` (currently lines ~64–93)

Rewrite the per-Well loop:

- Build the present Channels list, excluding any whose Call is `"ROX Unavailable"` (and any missing/empty value).
- Compute `perTube[i]` verdict by the precedence above (Detected-wins).
- Compute and return a new `perTubeLabel[i]` string holding the full dual-channel label (grouped/ordered as specified).
- `detectedCount` / `inconclusiveCount` continue to count `perTube` verdicts — no formula change, but values shift because of the new precedence.
- Also compute and return a channel-level inconclusive flag, e.g. `anyChannelInconclusive` — `true` if any Channel Call on any Well is `Inconclusive` (excluding `ROX Unavailable`). This is what QC Status reads, independent of the verdict.
- `perTubeDetectedLabels` (current detected-only labels) is superseded by `perTubeLabel`; remove it unless still referenced.

### Pill render (currently lines ~193–207)

Replace the inline `labelDetail` computation with `summary.perTubeLabel[index]`. Keep the `run-detail-pill--${status}` color class driven by `summary.perTube[index]`.

### `qcStatus` (currently line ~149)

Change the basis from the Well Verdict to the Channel Calls. Replace
`summary.inconclusiveCount > 0 ? "Review" : "Pass"` with
`summary.anyChannelInconclusive ? "Review" : "Pass"`. This keeps QC sensitive to
an inconclusive Channel even when the Well Verdict is Detected (Detected-wins),
so an inconclusive result is never passed.

### Run-level "Result" line (`formatResultSummary`, lines ~41–62)

Out of scope for format changes. It already derives from `perTube`, so its values shift automatically with the new precedence. Leave its format as-is unless a follow-up requests otherwise.

---

## Tests

The frontend is plain-HTML-no-build (ADR-003) and `summarizeResults` is not exported — there is no JS unit-test runner. Test via **Playwright e2e**, mirroring `tests/e2e/test_results_display.py`:

- Seed a history entry / results fixture for each row of the verdict and pill-text tables above (mixed FAM/ROX combinations, both-same combinations, and a `ROX Unavailable` fixture).
- Assert: the per-tube pill **text** matches the expected dual-channel string; the pill **color class** matches the expected verdict; the `Detected` / `Inconclusive` KPI counts are correct; the `QC Status` badge reads as expected.
- Include the key QC case explicitly: a run whose only inconclusive signal is on a Channel of a Detected-verdict Well (e.g. `Detected(FAM) + Inconclusive(ROX)`) must show `Detected: 1/4`, `Inconclusive: 0/4`, **and `QC Status: Review`** — proving QC is channel-sensitive, not verdict-driven.
- Add a fixture with custom profile labels to assert dye-label substitution.

> Pure-logic unit tests would require exporting `summarizeResults` + adding a JS test runner, which conflicts with ADR-003. e2e is the pragmatic path; flag if the team wants to revisit.

---

## Files touched

| File | Change |
|---|---|
| `aquila_web/static/history_detail.js` | New verdict precedence + `perTubeLabel`; pill render uses it |
| `tests/e2e/` + `tests/fixtures/results/` | New e2e tests + fixtures for verdict/label/KPI/QC cases |
| `CONTEXT.md` | Added **Well Verdict** term (done) |

## Out of scope

- The live run page (`script.js`) — unchanged.
- `formatResultSummary` text format — unchanged (values reflect new precedence).
- Any backend / stored-Call changes — the data model `Call` values are untouched; this is presentation/aggregation only.
