# PRD: Structured Profile Editor

> Status: Ready for agent
> Related: ADR-018 (Structured Profile Editor — Backend-Assembled Steps with `stages` as Source of Truth), ADR-003 (plain HTML/CSS/JS, no build step)
> Glossary: `CONTEXT.md` — Stage, Sub-stage, Step, Boilerplate, Structured Profile, Legacy Profile

## Problem Statement

Operators creating a PCR Profile today face a fully generic step builder that exposes raw hardware steps (`setpoint`, `ramp_rate`, `enable`/`disable`, fan on/off) and forces them to hand-author the same fixed equilibration, fan, optics, and cooldown scaffolding on every Profile. This is error-prone (an operator can omit or misconfigure scaffolding that every valid assay needs) and presents the assay in hardware terms rather than the domain terms a scientist thinks in (Incubation, Denaturation, Amplification, Final Hold). There is no guardrail against out-of-range temperatures or durations.

## Solution

Replace the generic builder — for new and structured Profiles — with a guided editor that presents only the four domain Stages the operator actually controls (Incubation, Initial Denaturation, Amplification, Final Temp Hold) plus the Amplification cycle count. Each optional Stage is toggled by a checkbox; Amplification is always present and supports 2–3 Sub-stages. All fixed scaffolding (Boilerplate) — equilibration, fan control, optics init, entry/exit ramps, the per-cycle optics read, and cooldown — is applied automatically by the backend and never shown to the operator. Field-level validation keeps temperatures and durations in the instrument's safe range. The operator's selections are saved as a `stages` object that is the editable source of truth; the backend regenerates the runnable `steps` from it on every save. Profiles created before this feature (Legacy Profiles) open read-only in the app and remain hand-editable on disk.

## User Stories

1. As an operator, I want to name a new Profile, so that I can identify it later in the Profiles list.
2. As an operator, I want to set the FAM and ROX channel labels on a Profile, so that results are reported against my biological targets.
3. As an operator, I want to optionally record an estimated completion time in minutes, so that the run screen can show a countdown.
4. As an operator, I want a fresh Profile to open with all four Stages enabled but every field blank, so that I explicitly enter every value rather than trusting hidden defaults.
5. As an operator, I want to enable or disable the Incubation Stage with a checkbox, so that I only include it when my assay needs it.
6. As an operator, I want to enable or disable the Initial Denaturation Stage with a checkbox, so that I only include it when my assay needs it.
7. As an operator, I want to enable or disable the Final Temp Hold Stage with a checkbox, so that I only include it when my assay needs it.
8. As an operator, I want the Amplification Stage to always be present, so that every Profile produces an amplification program.
9. As an operator, I want to set a temperature and time for each enabled Stage, so that I define the thermal program.
10. As an operator, I want disabled (unchecked) Stages to grey out and become uneditable, so that I can clearly see which Stages are inactive.
11. As an operator, I want the values in a Stage I just unchecked to be preserved, so that if I re-check it I get my original entries back instead of having to retype them.
12. As an operator, I want an unchecked Stage to produce no entries in the saved Profile, so that disabled Stages have zero effect on the run.
13. As an operator, I want the Amplification Stage to start with two Sub-stages (Denaturation and "Annealing & Extension"), so that I have the common two-step amplification by default.
14. As an operator, I want to add a third Amplification Sub-stage, so that I can run a three-step amplification.
15. As an operator, when I add a third Sub-stage, I want the second Sub-stage to be renamed from "Annealing & Extension" to "Annealing" and the new third to be named "Extension", so that the naming reflects a three-step program.
16. As an operator, I want to remove the third Sub-stage, so that I can revert to a two-step amplification.
17. As an operator, when I remove the third Sub-stage, I want the second Sub-stage's name reverted to "Annealing & Extension", so that the naming reflects a two-step program again.
18. As an operator, I want to be prevented from having fewer than two or more than three Amplification Sub-stages, so that I can't build an invalid amplification.
19. As an operator, I want to set a temperature and time for each Amplification Sub-stage, so that I define each step of the cycle.
20. As an operator, I want to set the Amplification cycle count, so that the amplification repeats the right number of times.
21. As an operator, I want the optics read to be taken automatically during the extension portion of each cycle, so that fluorescence is measured without my having to place a read step.
22. As an operator, I want all the fixed instrument scaffolding (equilibration, fan, ramps, cooldown) handled automatically, so that I don't have to author it and can't get it wrong.
23. As an operator, I want a temperature outside 25–100 °C to be rejected with an "Invalid Value" error highlighted in red, so that I can't save a Profile the instrument can't run.
24. As an operator, I want a time outside 1–600 s to be rejected with an "Invalid Value" error highlighted in red, so that I can't save an out-of-range duration.
25. As an operator, I want the extension-bearing Sub-stage to require at least 11 s, so that the automatic optics split is always valid.
26. As an operator, I want a non-numeric entry in any field to be rejected with an "Invalid Value" error, so that garbage values never reach a run.
27. As an operator, I want a cycle count outside 1–50 to be rejected with an "Invalid Value" error, so that the cycle count stays valid.
28. As an operator, I want validation errors to appear only when I try to save (not while the form is still blank on first load), so that a fresh form doesn't look broken.
29. As an operator, I want every offending field flagged red simultaneously on a failed save, so that I can see all the problems at once.
30. As an operator, I want save blocked until every enabled field is valid, so that I can't persist an invalid Profile.
31. As an operator, I want fields in disabled Stages to be skipped by validation, so that blanks in inactive Stages don't block my save.
32. As an operator, I want to save my Profile and return to the Profiles list, so that I can run or manage it.
33. As an operator, I want to re-open a Profile I created in the structured editor and see all my Stages, Sub-stages, and values restored, so that I can edit it.
34. As an operator, I want my edits to a structured Profile to regenerate the run program correctly, so that the saved Profile reflects my changes.
35. As an operator, I want Legacy Profiles (created before this feature) to open in a read-only view, so that I can inspect them without risking accidental edits.
36. As an operator, I want bundled Profiles to remain read-only, so that shipped assays can't be altered in the app.
37. As an operator, I want the Profiles list to take me to the structured editor for structured Profiles and the read-only view for Legacy Profiles, so that each Profile opens in the right place.
38. As an operator, I want to start a run from any Profile regardless of how it was authored, so that older Profiles keep working.
39. As a developer, I want to hand-edit a Legacy Profile's JSON file on disk, so that I can still maintain old Profiles outside the app.
40. As a developer, I want adding a valid `stages` block to a Profile file to promote it to a Structured Profile, so that there's a manual upgrade path.
41. As a developer, I want the backend to re-validate the submitted Stages, so that an out-of-range value can't bypass the form and reach disk.
42. As a developer, I want the boilerplate assembly logic to live server-side in one place, so that it's unit-testable and not duplicated in the browser.

## Implementation Decisions

**Contract (shared, built first).** `ProfileSave` gains an optional `stages` field. The structured editor POSTs `{ name, fam_label, rox_label, estimated_minutes, stages }` (no `steps`). The `stages` object shape:

```
stages: {
  incubation:    { enabled: bool, temp: number, time: number },   // seconds
  denaturation:  { enabled: bool, temp: number, time: number },
  amplification: {
    cycles: number,
    subStages: [ { name: string, temp: number, time: number }, ... ]  // length 2 or 3
  },
  finalHold:     { enabled: bool, temp: number, time: number }
}
```

`amplification` has no `enabled` (always present). A committed sample fixture of this object is the contract artifact both routes build against.

**Storage & tagging.** A Structured Profile's JSON carries the `stages` object (editable source of truth) plus the backend-generated `steps`. The presence of `stages` is the only marker that a Profile is structured — no separate version flag. `steps` is regenerated from `stages` on every save and is never reverse-parsed.

**Backend step assembly.** A pure function expands `stages` into `steps`, in order:
- Head (always): `disable`/1s ("Record equilibration without power.") → `ramp_rate` 1.6 → `pcr_fanon` 1 → `enable`/1s → `optics` → `setpoint` 25 °C/1s ("Presetting temperature").
- Incubation (if enabled): one `setpoint` (temp/time, description "Incubation").
- Initial Denaturation (if enabled): one `setpoint` (temp/time, description "Initial Denaturation").
- Amplification (always): `ramp_rate` 1.75, then a `repeat` block over the Sub-stages with `cycles` = cycle count. Each Sub-stage is one `setpoint` (description = current Sub-stage name). The extension-bearing Sub-stage (the 2nd of two, or the 3rd of three) is split so the optics read fires inside it: `setpoint`(temp, time−10) → `optics` → `setpoint`(temp, 10).
- Final Temp Hold (if enabled): one `setpoint` (temp/time, description "Final Temp Hold"), placed after Amplification and before the tail.
- Tail (always): `ramp_rate` 1.6 → `setpoint` 40 °C/20s ("Initial cooling") → `setpoint` 25 °C/10s ("Restoring setpoint to RT") → `disable`/5s → `pcr_fanoff` 0.
- Unchecked Stages emit no steps.
- Top-level keys preserved: `output_dir` ("pcr_data"), `post_in_gui` ("True"), `title`, `labels` {fam, rox}.

**Backend validation.** A pure validation function re-checks the submitted `stages`: temp 25–100 °C; time 1–600 s; extension-bearing Sub-stage time 11–600 s; cycles integer 1–50; Sub-stage count 2 or 3. Disabled Stages are skipped. Invalid input returns an error response (existing 4xx convention on `POST /profiles`), not a written file.

**List & detail endpoints.** `GET /profiles` returns a `structured` boolean per Profile (true iff its JSON has `stages`) so the list can route rows. `GET /profiles/details` returns the `stages` object when present so the editor can repopulate.

**Estimated time.** The manual optional "Est. Time (Min)" field and its existing `estimated_minutes` → `estimated_completion_seconds` / `time_unavailable` handling are retained unchanged. It is not auto-computed (true runtime depends on machine movement/heat-up and can't be derived from setpoints).

**Frontend editor (new files).** A new structured editor (e.g. `profile_builder.html` + `profile_builder.js`) on a new route, served by a single backend route added in the shared upfront task. Plain HTML/CSS/JS, no build step (ADR-003). Responsibilities: render the four Stages with checkboxes; grey/disable unchecked Stages while preserving their values; Amplification Sub-stage add/remove with the rename transitions and the 2–3 bound; save-triggered validation that flags every blank/non-numeric/out-of-range enabled field red with "Invalid Value" and blocks save; POST the `stages` payload; repopulate from `stages` on edit.

**List routing & legacy view (frontend).** The Profiles list routes a row by its `structured` flag: structured → the new editor; Legacy → the existing `edit_form.html` in its read-only `?view=1` mode (Legacy rows get a "View" affordance, not "Edit"). Bundled Profiles stay read-only as today.

**Branching.** Integration branch `feature/structured-profiles` off `main`; `…-backend` and `…-frontend` branch off it and PR back into it; integration merges to `main` as one reviewed PR. The only `main.py` region both routes would touch — the route that serves the new editor HTML — is done in the shared upfront task so the two route branches stay disjoint.

## Testing Decisions

Good tests assert external behavior at the highest available seam — the shape of the written Profile JSON, the HTTP response, and observable DOM behavior — not internal function structure. Three seams, matching the split:

**Seam 1 — Backend assembly (unit).** New `unit_tests/test_profile_assembly.py` exercising the pure `stages → steps` assembly and the validation function directly: head/tail constants and ordering; mid ramp 1.75 before the `repeat`; optics split `(time−10) / 10` on the correct Sub-stage for both 2- and 3-Sub-stage cases; unchecked Stages omitted; Sub-stage names in descriptions; cycles wrapping; Final Temp Hold placement; every validation boundary (25/100 °C, 1/600 s, extension 11 s, cycles 1/50, Sub-stage count). Prior art: `unit_tests/test_estimated_completion.py` (stubs hardware deps, imports `aquila_web.main`, marked `unit`).

**Seam 2 — Backend HTTP contract (contract).** Extend `tests/contract/test_profile_endpoints.py` (FastAPI TestClient, marked `contract`): POST a `stages` payload → 200, written JSON has correct `steps` and a round-trippable `stages`; out-of-range / blank / wrong Sub-stage count → error, nothing written; `GET /profiles` returns `structured` true for a structured Profile and false for a legacy one; `GET /profiles/details` returns `stages` for a structured Profile and omits it for a legacy one. Prior art: existing `test_profile_endpoints.py`, `test_bundled_profiles.py`.

**Seam 3 — Frontend builder (e2e).** New `tests/e2e/test_profile_builder.py` (Playwright, marked `e2e`): fresh form opens with all Stages on and fields blank, no errors shown; unchecking greys a Stage and preserves its values on re-check; adding/removing the third Sub-stage applies the rename transitions and enforces the 2–3 bound; Save with blanks/invalid flags the offending fields red with "Invalid Value" and does not navigate; a valid Save POSTs the expected `stages` payload and redirects to the Profiles list; a structured Profile re-opens repopulated; a Legacy Profile opens read-only. Prior art: `tests/e2e/test_countdown_timer.py`, `tests/e2e/test_run_dropdowns.py`.

The full suite (`pytest tests unit_tests -v`) must pass, including existing profile/bundled tests, per CLAUDE.md.

## Out of Scope

- Reverse-parsing arbitrary Legacy `steps` into the structured model — Legacy Profiles are read-only in-app by design (ADR-018).
- In-app editing of Legacy or bundled Profiles (hand-editing the JSON on disk remains the path).
- Auto-computing estimated completion time.
- Exposing ramp rates, fan control, optics placement, or equilibration/cooldown as operator-editable fields — these are fixed Boilerplate.
- Per-Sub-stage configurable optics offset (the 10 s tail is a fixed constant).
- Changes to the run flow, analytics, Sync, or the `run_complete` event payload.
- Profile name uniqueness / filename-collision policy beyond the existing sanitization behavior.

## Further Notes

- The optics split tail (10 s) and ramp constants (head/tail 1.6, mid 1.75) and preset temp (25 °C) are hardcoded per ADR-018; changing them is a code + test change, not a Profile edit.
- The `steps` array remains the only artifact the hardware runner and analytics read; `stages` is additive and ignored by the runner.
- A hand-edit to a structured Profile's `steps` that isn't mirrored in `stages` will be overwritten on the next structured save — `stages` wins.
- The 25 °C floor on Final Temp Hold (and all temps) matches the instrument's cooldown floor; sub-ambient holds are not supported.
