# ADR-012: Custom Dropdowns Are Cosmetic Overlays Over Native Form Controls

**Status:** Accepted
**Date:** 2026-06-16
**Author:** Rasita Vajapattana
**Deciders:** Aquila Engineering Team

---

## Context

The Run screen renders form controls (the Profile picker, the dev-only optics-path
input) whose appearance is decided by the browser/OS, not the app. On the kiosk fleet
(ADR-005: Chromium kiosk on Raspberry Pi) this means the native `<select>` option list
and the native autofill dropdown render with OS styling — dark background, system font,
no border radius — which is visually inconsistent across machines and clashes with the
themed UI. Kiosk units must look identical, so app-controlled styling is required
(issue #166).

The Profile `<select>` is not merely decorative: its value feeds run execution. The
selected profile is read on run start (`/profile/select`), drives dye-label loading,
and is preselected from the URL (`?profile=`) and `/button_status`. Existing reads rely
on the standard `<select>` API (`value`, `selectedOptions`) and the `change` event.

Constraints:
- ADR-003: plain HTML/CSS/JS, no build step, no framework, manual component reuse.
- A native `<select>`'s open option list cannot be themed by the app — the OS owns it.

Live options were: (a) replace the native control entirely with a custom widget and
rewrite every reader, or (b) keep the native control as a hidden source of truth and
layer a themed widget on top.

Doing nothing leaves the UI visually inconsistent across the fleet.

---

## Decision

**We will build custom dropdowns as cosmetic overlays that leave the native form
control in the DOM as the hidden source of truth.**

Concretely, for the Profile picker:

- `<select id="mySelect">` remains in the DOM, hidden (`display:none`). It stays the
  authoritative value holder.
- A themed `<button>` + `<ul role="listbox">` render the visible UI, mirroring the
  select's `<option>`s.
- Selecting a custom option writes the value to the hidden `<select>` and **dispatches
  a synthetic `change` event**, so all existing readers and the `/profile/select` flow
  work unmodified.

The same principle applies to other native controls restyled in this codebase: restyle
on top, never rip out the working control. (The dev-only optics field is an analogous
custom typeahead over an existing `<input>`; the Run Name field suppresses native
autofill via `autocomplete="off"` rather than replacing the input.)

This is **reversible with effort** — the overlay can be removed to fall back to the
native control — but the hidden control must not be deleted while the overlay exists.

---

## Consequences

### Positive
- Appearance is app-controlled and identical across the fleet (the issue's goal).
- Run execution is untouched: the cosmetic change carries near-zero regression risk to
  the run flow, and existing contract tests (`test_ready_screen_run_flow.py`) still
  characterize real behavior through the unchanged `change`/`value` seam.
- No framework or build step required — fits ADR-003.

### Negative
- Two representations of the same state (hidden control + visible overlay) must be kept
  in sync; a sync bug shows stale labels.
- A future reader may see the hidden `<select>` as dead code and be tempted to remove
  it, which would silently break run execution. (This ADR exists to prevent that.)

### Neutral / Tradeoffs
- The overlay duplicates listbox/keyboard/dismissal behavior the browser gives for free
  on a native control. On a touch kiosk this is acceptable; keyboard navigation is built
  but only meaningfully exercised on the dev-only optics field.

---

## Alternatives Considered

### Option A: Replace the native `<select>` entirely with a custom widget
**Why rejected:** Forces rewriting every reader of the profile value and re-testing the
whole run flow for a purely cosmetic change — high risk, no behavioral benefit.

### Option B: Restyle the native control's option list with CSS
**Why rejected:** Not possible — the OS owns the rendering of an open `<select>` list;
CSS cannot theme it consistently across machines.

---

## Revisit Conditions

- If the project ever adopts a frontend framework (reversing ADR-003), prefer a real
  component over the hidden-control overlay pattern.
- If keeping the hidden control and overlay in sync becomes a recurring source of bugs,
  revisit Option A (full replacement) with proper test coverage.

---

## References

- Related ADRs: ADR-003 (plain HTML/no build), ADR-005 (kiosk host)
- Issue: #166
- Spec: `specs/frontend/run-dropdowns-spec.md` (PR #170)
