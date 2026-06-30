# ADR-018: Structured Profile Editor — Backend-Assembled Steps with `stages` as Source of Truth

**Status**: Accepted
**Date**: 2026-06-25
**Deciders**: Aquila Engineering Team

---

## Context

The current profile editor (`aquila_web/static/profiles/edit_form.html` + `edit.js`) is a fully generic step builder: operators add arbitrary stages and choose raw step types (`setpoint`, `ramp_rate`, `enable`, `disable`, `pcr_fanon`, `pcr_fanoff`). This exposes hardware-level detail that operators get wrong, and every assay must hand-author the same fixed equilibration/fan/optics/cooldown scaffolding (visible identically across all bundled profiles, e.g. `ABBA_ramp1.75_EA30.json`).

We are introducing a guided, structured editor that presents only four domain Stages — Incubation, Initial Denaturation, Amplification, Final Temp Hold — plus the Amplification cycle count. Everything else (equilibration, fan control, optics init, entry/exit ramps, the optics read inside each cycle, cooldown) must be applied automatically and consistently.

Two cross-cutting facts forced the architectural decisions below:

- **The work is split across two engineers** who must proceed concurrently without blocking each other, which demands a clean, agreed contract between the form and the file.
- **Existing profiles have arbitrary step structures** that do not map cleanly into four fixed Stages, so a rigid editor cannot safely round-trip them.

Per ADR-003, the frontend has no build step — the editor is plain HTML/CSS/JS served by FastAPI.

---

## Decision

**We will add a structured profile editor as new files alongside the existing editor, persist the operator's choices as a `stages` object that is the single editable source of truth, and have the backend assemble the runnable `steps` array from a fixed boilerplate template.**

Concretely:

- **New files, not a rewrite.** The structured editor ships as new artifacts (e.g. `profile_builder.html` / `profile_builder.js`) on a new route. The existing `edit_form.html` / `edit.js` is retained solely to render the read-only Legacy view via its existing `?view=1` mode.
- **`stages` is the source of truth and the tag.** A Structured Profile's JSON carries a top-level `stages` object (the four Stages with `enabled`/temp/time, plus Amplification's `cycles` and 2–3 `subStages`). Its presence is the *only* marker distinguishing a Structured Profile from a Legacy Profile — no separate version flag.
- **Backend assembles `steps`.** The frontend POSTs `{title, labels, estimated_minutes, stages}`. The backend validates `stages`, then expands them into the full `steps` array: fixed head (`disable/1s → ramp 1.6 → pcr_fanon → enable/1s → optics → 25°C/1s`), enabled Stages in order, the mid ramp `1.75` before the Amplification `repeat`, the optics read split inside the extension-bearing sub-stage (`(t−10)s → optics → 10s`), the Final Temp Hold before the tail, and the fixed tail (`ramp 1.6 → 40°C/20s → 25°C/10s → disable/5s → pcr_fanoff`). `steps` is regenerated on every save and is **never reverse-parsed** back into `stages`.
- **`steps` remains the only thing the hardware runner and analytics read.** `stages` is purely additive; the runner ignores it. Re-editing reads `stages`.
- **Legacy Profiles are read-only in-app.** Any profile without `stages` (everything predating this feature, plus all bundled profiles) opens read-only; it stays runnable and hand-editable as a JSON file on disk. `GET /profiles` returns a `structured` flag so the list routes each row to the builder (structured) or the read-only view (legacy).

This decision is **hard to reverse**: it defines the on-disk JSON contract, what is written to every new profile, and what executes on hardware.

---

## Consequences

### Positive
- Operators author assays in domain terms; hardware scaffolding can't be mis-entered or forgotten.
- Boilerplate constants and the optics-split rule live server-side in one place, unit-testable in `unit_tests/` (per CLAUDE.md), not duplicated in browser JS.
- Lossless round-trip: re-opening reads `stages` directly, sidestepping the unsolved problem of mapping arbitrary `steps` back into four Stages.
- Clean two-engineer split: the `stages` payload is the contract; frontend and backend build against it independently.
- Additive `stages` key means zero blast radius for the runner and analytics.

### Negative
- The JSON carries redundant data (`stages` plus the derived `steps`); a hand-edit to `steps` that isn't mirrored in `stages` will be silently overwritten on the next structured save.
- Two editor frontends coexist (structured builder + legacy read-only viewer).
- Boilerplate constants (1.6 / 1.75 / 25°C / 10s optics offset) are hardcoded; changing assay scaffolding requires a code + test change, not a profile edit.

### Neutral / Tradeoffs
- Local Legacy Profiles lose in-app editability (previously editable); mitigated by the on-disk hand-edit escape hatch and the fact that adding a valid `stages` block promotes a file to Structured.
- The manual "Est. Time (Min)" field is retained rather than auto-computed — runtime can't be derived accurately from setpoints (machine movement/heat-up), so a manual estimate stays honest.

---

## Alternatives Considered

### Frontend assembles `steps` (status quo pass-through)
**Why rejected:** buries hardware/domain logic in browser JS, can't be unit-tested server-side, and collapses the clean contract seam the two-engineer split depends on.

### Single editor (rewrite `edit.js` to branch internally)
**Why rejected:** mixes a rich structured builder and a legacy step-dump in one risky rewrite of working code; new-files-alongside isolates the new UI as an ownable artifact.

### Reverse-parse `steps` into `stages` on edit (no stored `stages`)
**Why rejected:** arbitrary thermal programs don't map cleanly into four fixed Stages; reverse-parsing is lossy and could silently drop steps a scientist relied on.

### Optics read placed after a single hold (no split)
**Why rejected:** every shipped assay reads mid-hold; a single-hold read diverges from validated profiles. The `(t−10)s → optics → 10s` split reproduces current behavior.

---

## Revisit Conditions

- If a third assay shape emerges that the four-Stage model can't express, revisit whether `stages` should become a more general schema.
- If boilerplate constants need to vary per assay, revisit hardcoding them (promote to config or per-profile fields).
- If maintaining two editor frontends becomes a burden, revisit folding the Legacy read-only view into the builder.

---

## References

- Related ADRs: ADR-003 (plain HTML/CSS/JS, no build step), ADR-006 (JSON state-machine UI screens)
- Glossary: `CONTEXT.md` — Stage, Sub-stage, Step, Boilerplate, Structured Profile, Legacy Profile
- Code: `aquila_web/main.py` (`POST /profiles`, `GET /profiles`, `GET /profiles/details`), `aquila_web/static/profiles/`
