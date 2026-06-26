# Frontend / UI Spec: Amplification Sub-stages — add/remove + rename + cycles (issue #202)

**Status:** Active
**Author:** Aquila Engineering Team
**Last updated:** 2026-06-25
**GitHub issue:** #202 (Structured Profiles B2)
**Affected screens:** Create Profile (`/profiles/builder`)
**Source file(s):** `aquila_web/static/profiles/builder.html`, `aquila_web/static/profiles/builder.js`, `aquila_web/static/styles.css`, `tests/e2e/test_profile_builder.py`
**Umbrella PRD:** `specs/prd/structured-profile-editor-prd.md` · **Decision:** ADR-018, ADR-003 (plain HTML/JS, no build)
**Depends on:** #200 (the builder shell — merged into `updated-profiles`)

---

## 1. Overview

B2 makes the Amplification Stage's Sub-stages interactive. B1 (#200) shipped two static Sub-stage rows; this issue lets the operator switch between a two-step and three-step amplification by adding/removing the third Sub-stage, with the name transitions the domain requires, bounded to 2–3 Sub-stages. The Amplification cycle count (the `#stage-amp-cycles` field shipped in B1) and the now-dynamic Sub-stage list both feed the posted `stages.amplification` object.

It deliberately does **not** validate field ranges or enforce the extension-bearing Sub-stage's 11 s minimum (B3 / A2), assemble `steps` or place the optics split (A1), or repopulate from a saved Profile on edit (later issue).

**Carry-over cleanups from the B1 PR review (#207), folded in because B2 edits these same files:**
- Fix the misleading `_goto_builder` comment in `test_profile_builder.py` that claims the Stages are JS-rendered (they are static HTML; `builder.js` only wires behavior).
- Bring tap targets to the spec's **≥44×44px** kiosk rule (§6): the new add/remove controls, and the existing B1 Stage enable checkbox whose 22px box + unpadded label currently misses it.

Context: plain HTML/CSS/JS, no build step (ADR-003); Chromium kiosk on the 768×1024 Pi touch display (ADR-005).

---

## 2. Screen Inventory

| Screen ID | Name | Entry condition | Exit conditions |
|-----------|------|----------------|-----------------|
| `builder` | Create Profile | Navigate to `/profiles/builder` | Save → Profiles list; Back/Cancel → Profiles list |

No new screens — this extends the Amplification card on the existing builder.

---

## 3. State Machine Transitions

Sub-stage count is a small local state machine inside the Amplification card:

```
[2 sub-stages] --[+ Add sub-stage tab]----> [3 sub-stages]
[3 sub-stages] --[Extension row's X]-------> [2 sub-stages]
```

- At `[2]`: add tab visible, no `X` present. At `[3]`: add tab hidden, Extension row carries the `X`. Count never leaves {2, 3}.

---

## 4. Screen Designs

### Amplification card (`#stage-amplification`)

**Sub-stage names are display labels driven by the count, not editable inputs:**

| Count | Sub-stage 0 | Sub-stage 1 | Sub-stage 2 |
|-------|-------------|-------------|-------------|
| 2 (two-step) | `Denaturation` | `Annealing & Extension` | — |
| 3 (three-step) | `Denaturation` | `Annealing` | `Extension` |

Each Sub-stage row keeps its B1 DOM shape: a name label `#stage-amp-sub-{i}-name` and temp/time inputs `#stage-amp-sub-{i}-temp` / `#stage-amp-sub-{i}-time` (`i` = 0,1,2).

**Card layout (top → bottom):** Amplification header → the Sub-stage rows → the add-tab (when at two) → **Cycles** (`#stage-amp-cycles`) as the last field. Cycles sits at the bottom of the card, below the last Sub-stage.

**Controls:**
- Add: `#amp-add-substage` — a **full-width "+ Add sub-stage" tab** rendered below the Sub-stage rows. Visible **only at two Sub-stages**; hidden once a third exists.
- Remove: `#amp-remove-substage` — an **`X` button on the right of the Extension row's header**. It exists **only while the third Sub-stage exists** (created with that row), not a persistent control.

**Interactions:**
- **Add (count 2 → 3):** rename Sub-stage 1's label `Annealing & Extension` → `Annealing`; append a third row `#stage-amp-sub-2-*` named `Extension` (blank temp/time) carrying its `X` remove button; **hide the add tab**.
- **Remove via the Extension row's `X` (count 3 → 2):** delete the third row; rename Sub-stage 1's label back to `Annealing & Extension`; **show the add tab** again.
- A fresh builder opens at count 2 (two-step) with the add tab visible and no `X`, matching B1.

**Touch targets:** the add tab and the Stage enable checkbox (B1, via its `.stage__toggle` label) guarantee a ≥44×44px hit area. The Extension row's `X` is a deliberate exception — kept compact (red, no 44px minimum) so the Extension header is the same height as a plain Sub-stage name and the spacing between Sub-stages stays uniform; it trades the touch minimum for visual rhythm on this one rarely-used control.

**Error states:** none in B2 (validation is B3). The 2–3 bound is enforced structurally by the disabled controls, not by an error message.

---

## 5. Data Binding

### Save payload — `stages.amplification`

The amplification object in the POST body becomes **dynamic** over the rendered Sub-stage rows (B1 hardcoded exactly two):

```json
"amplification": {
  "cycles": <number|null>,
  "subStages": [
    { "name": "<row 0 label>", "temp": <number|null>, "time": <number|null> },
    { "name": "<row 1 label>", "temp": <number|null>, "time": <number|null> }
    // ...plus row 2 when present (three-step)
  ]
}
```

Binding rules:
- `subStages` is built by iterating the rendered `.amp-substage` rows in DOM order — length 2 or 3 — reading each row's name label and its temp/time inputs. Names reflect the current two-/three-step state.
- `cycles` = `#stage-amp-cycles` (blank ⇒ `null`, else `Number`). No validation in B2 (B3).
- All other payload fields (`name`, `fam_label`, `rox_label`, `estimated_minutes`, and the other three Stages) are unchanged from B1.

---

## 6. Accessibility / Kiosk Constraints

- All interactive controls ≥ 44×44px (frontend spec §6; 768×1024 Pi kiosk). This is a hard criterion B2 must satisfy for its add/remove controls **and** retroactively for the B1 Stage checkbox.
- No hover-only affordances; disabled controls visibly non-interactive.

---

## 7. Assets

| Asset | Path | Notes |
|-------|------|-------|
| Builder markup | `aquila_web/static/profiles/builder.html` | Add the add/remove controls; the third Sub-stage row is created in JS on demand. |
| Builder script | `aquila_web/static/profiles/builder.js` | Sub-stage add/remove + rename + bound enforcement; dynamic `subStages` in `buildPayload`. |
| Styles | `aquila_web/static/styles.css` | Add/remove control sizing; checkbox ≥44px hit area. |

---

## 8. Acceptance Criteria

- [ ] Amplification starts with exactly two Sub-stages named `Denaturation` and `Annealing & Extension`.
- [ ] The full-width add tab shows at two Sub-stages; adding a third renames Sub-stage 1 to `Annealing`, appends a blank `Extension` row, and hides the add tab.
- [ ] The Extension row carries an `X` (right of its header); clicking it removes the third Sub-stage, reverts Sub-stage 1's name to `Annealing & Extension`, and brings the add tab back.
- [ ] Count is bounded to {2, 3}: no `X` at two, no add tab at three.
- [ ] Cycles is the last field in the Amplification card (below the Sub-stages).
- [ ] The posted `stages.amplification` reflects the current Sub-stages (2 or 3, with correct names) and `cycles`.
- [ ] The add tab and the B1 Stage enable checkbox meet the ≥44×44px touch-target rule (the Extension `X` is intentionally exempt, kept compact for uniform spacing).
- [ ] The Extension `X` is red and small enough that the gap between Sub-stages 2 and 3 matches the gap between 1 and 2.
- [ ] `_goto_builder`'s comment in `test_profile_builder.py` no longer claims the Stages are JS-rendered.
- [ ] e2e in `tests/e2e/test_profile_builder.py` covers add/remove + the rename transitions and the 2–3 bound; existing B1 tests still pass.

---

## Out of Scope (other issues, other specs)

- Field validation, "Invalid Value" highlighting, the extension-bearing Sub-stage's 11 s minimum, save-blocking — B3 (#203) / A2 (#199).
- Assembling `stages → steps` and placing the optics split inside the extension Sub-stage — A1 (#198).
- Repopulating the builder (including 3-Sub-stage state) from a saved Profile on edit, and Profiles-list routing — B3 (#203).
- Making Sub-stage names free-text editable — they remain count-driven labels.

---

## 9. Open Questions

- [ ] None — Sub-stage transitions and the 2–3 bound are fixed by PRD user stories 13–18 and ADR-018.
