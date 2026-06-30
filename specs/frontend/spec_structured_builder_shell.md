# Frontend / UI Spec: Structured Builder Shell — Stages, Checkboxes, Save (issue #200)

**Status:** Active
**Author:** Aquila Engineering Team
**Last updated:** 2026-06-25
**GitHub issue:** #200 (Structured Profiles B1)
**Affected screens:** Create Profile (`/profiles/builder`)
**Source file(s):** `aquila_web/static/profiles/builder.html`, `aquila_web/static/profiles/builder.js` (new), `aquila_web/static/styles.css`
**Umbrella PRD:** `specs/prd/structured-profile-editor-prd.md` · **Decisions:** ADR-018, ADR-003 (plain HTML/JS, no build)
**Depends on:** #197 (the `stages` contract + `/profiles/builder` route — merged)

---

## 1. Overview

The structured profile builder's first vertical slice: render the fixed top fields and the four domain Stages into the editor shell (`#profile-builder-root`, served by `/profiles/builder` from #197), let the operator toggle the three optional Stages with checkboxes, and POST a `stages` payload that redirects to the Profiles list.

This is the **shell only**. It deliberately does **not** validate fields, display "Invalid Value" errors, drive Amplification Sub-stage add/remove, or repopulate from an existing Profile — those are B3 (#202), B2 (#201/#199 area), and the edit/list-routing issues. The backend stores `stages` verbatim (#197); assembly into `steps` and `POST` validation are A1/A2/A3 and are not exercised here.

Context: plain HTML/CSS/JS, no build step (ADR-003); Chromium kiosk on the Pi display, 768×1024 touch viewport (ADR-005).

---

## 2. Screen Inventory

| Screen ID | Name | Entry condition | Exit conditions |
|-----------|------|----------------|-----------------|
| `builder` | Create Profile | Navigate to `/profiles/builder` (from Profiles list "Create" — wired later) | Save success → Profiles list; Back/Cancel → Profiles list |

---

## 3. State Machine Transitions

```
profiles-page --[Create]--> builder
builder       --[Save success (POST /profiles 200)]--> profiles-page
builder       --[Back ‹ / Cancel]--> profiles-page
```

No in-page screen states in B1 (validation error state is B3).

---

## 4. Screen Designs

### Screen: `builder`

Renders inside the existing shell's `<div class="profile-form" id="profile-builder-root">`. Reuses the existing form CSS vocabulary (`card`, `field-grid`, `field`, `form-action-btn`, `button-row`, `is-hidden`).

**Layout (top → bottom):**

1. **Details card** (`#builder-details`) — fixed top fields, mirroring `edit_form.html`:
   - Profile name — `#profile-name` (text).
   - FAM Label — `#profile-fam-label` (text, pre-filled `"FAM"`). ROX Label — `#profile-rox-label` (text, pre-filled `"ROX"`). *(Mirrors `edit_form.html`'s defaults — decided over a fully-blank form so a quick save still carries sensible channel labels. The "every field blank" rule in #200 applies to the thermal value fields below.)*
   - Est. Time (Min) — `#profile-estimated-minutes` (number, `min="1"`, `placeholder="(Optional)"`). Retains the existing estimated-minutes behavior (blank ⇒ `null`).

2. **Four Stage cards**, in order. Each optional Stage is a `card stage` with an enable checkbox in its header; Amplification has no checkbox.

   | Stage | DOM id | Checkbox | Fields (all blank on fresh form) |
   |-------|--------|----------|----------------------------------|
   | Incubation | `#stage-incubation` | `#stage-incubation-enabled` (checked) | temp `#stage-incubation-temp`, time `#stage-incubation-time` |
   | Initial Denaturation | `#stage-denaturation` | `#stage-denaturation-enabled` (checked) | temp `#stage-denaturation-temp`, time `#stage-denaturation-time` |
   | Amplification | `#stage-amplification` | *(none — always present)* | cycles `#stage-amp-cycles`; 2 fixed Sub-stage rows (see below) |
   | Final Temp Hold | `#stage-finalhold` | `#stage-finalhold-enabled` (checked) | temp `#stage-finalhold-temp`, time `#stage-finalhold-time` |

   Temp/time/cycles inputs are `type="number"` `inputmode="numeric"`. Temp inputs carry the existing `keyboard-ignore`-style touch conventions as used elsewhere on the form (match `edit_form.html`).

   **Amplification Sub-stages (B1 = static).** Two rows are rendered with fixed name **labels** "Denaturation" and "Annealing & Extension", each with a temp and a time input (`#stage-amp-sub-0-temp/-time`, `#stage-amp-sub-1-temp/-time`), blank on a fresh form. **No add/remove controls and no rename transitions in B1** (that is B2). Sub-stage names are display labels, not editable inputs.

3. **Action row** (`button-row`): Save (`#save-profile-button`, primary) and Cancel (`<a href="/profiles-page">`). A `#save-status` line mirrors `edit_form.html`.

**Fresh-form initial state:**
- All three optional Stage checkboxes **checked (ON)**.
- Name and estimate blank; FAM/ROX pre-filled `"FAM"`/`"ROX"`; all temps, all times, **and cycles** blank.
- No error styling anywhere (no `field-error` shown; no red borders).

**User interactions:**
- Toggle a Stage checkbox OFF → the Stage card greys out (`.stage--disabled`) and **all its inputs get `disabled`**. The typed values are **kept in the DOM** (not cleared).
- Toggle it back ON → card un-greys, inputs re-enabled, previously typed values intact.
- Tap Save → build the `stages` payload (§5), `POST /profiles`, and on `200` redirect to `/profiles-page`.

**Error states (B1):** none rendered. A non-200 from `POST /profiles` sets `#save-status` to the response `detail` (or "Failed to save") and does **not** navigate — same failure handling as `edit.js`. Field-level "Invalid Value" highlighting is B3.

---

## 5. Data Binding

### Save payload — `POST /profiles`

Body (no `steps` — backend assembles those in A1/A3):

```json
{
  "name": "<#profile-name>",
  "fam_label": "<#profile-fam-label>",
  "rox_label": "<#profile-rox-label>",
  "estimated_minutes": <int|null>,
  "stages": {
    "incubation":   { "enabled": <bool>, "temp": <number|null>, "time": <number|null> },
    "denaturation": { "enabled": <bool>, "temp": <number|null>, "time": <number|null> },
    "amplification": {
      "cycles": <number|null>,
      "subStages": [
        { "name": "Denaturation",          "temp": <number|null>, "time": <number|null> },
        { "name": "Annealing & Extension", "temp": <number|null>, "time": <number|null> }
      ]
    },
    "finalHold":    { "enabled": <bool>, "temp": <number|null>, "time": <number|null> }
  }
}
```

Binding rules:
- `enabled` = the Stage checkbox's `checked` state. **All four stage keys are always present**; an unchecked Stage is sent with `enabled: false` (its preserved temp/time still ride along).
- Numeric fields: read `input.value`; an empty string ⇒ `null`, otherwise `Number(value)`. **No range/NaN validation in B1** (B3). The happy-path save uses in-range numeric values.
- `estimated_minutes`: reuse the existing rule — blank ⇒ `null`, else a positive integer (`Math.round(Number(...))`).
- `amplification.subStages` is always length 2 in B1 with the fixed names above.

### Redirect
On `response.ok`, `window.location.href = "/profiles-page"` (matches `edit.js`).

---

## 6. Accessibility / Kiosk Constraints

- Touch targets ≥ 44×44px; checkboxes sized for touch.
- No hover-only affordances.
- Disabled-Stage state must be visually obvious (greyed) and the inputs non-interactive (`disabled`), readable at arm's length on the 768×1024 display.

---

## 7. Assets

| Asset | Path | Notes |
|-------|------|-------|
| Builder shell | `aquila_web/static/profiles/builder.html` | Exists (#197); B1 fills `#profile-builder-root` and adds the `builder.js` script tag. |
| Builder script | `aquila_web/static/profiles/builder.js` | New. |
| Stage-disabled styling | `aquila_web/static/styles.css` | New `.stage--disabled` rule (grey + dim). |

---

## 8. Acceptance Criteria

- [ ] `GET /profiles/builder` renders the four Stage cards and the top fields into `#profile-builder-root`.
- [ ] Fresh form: all three optional Stages checked ON, thermal value fields (temps/times/cycles) blank, FAM/ROX pre-filled, no error styling shown.
- [ ] Unchecking a Stage greys it and disables its inputs; re-checking restores the previously typed values.
- [ ] An unchecked Stage is sent as `enabled: false` in the `stages` payload; all four stage keys always present.
- [ ] A valid Save POSTs the `stages` shape in §5 and redirects to `/profiles-page`.
- [ ] Plain HTML/CSS/JS, no build step (ADR-003); no change to `aquila_web/main.py`.
- [ ] e2e test `tests/e2e/test_profile_builder.py` (marked `e2e`) covers: default state, toggle/preserve, happy-path save. Prior art: `test_countdown_timer.py`, `test_run_dropdowns.py`.

---

## Out of Scope (other issues, other specs)

- Field validation, "Invalid Value" red highlighting, save-blocking — B3 (#202).
- Amplification Sub-stage add/remove, the 2↔3 rename transitions, and the 2–3 bound — B2.
- Repopulating the builder from an existing structured Profile on edit — later frontend issue.
- Profiles-list routing by the `structured` flag and the Legacy read-only view — later frontend issue.
- Backend `stages → steps` assembly and `POST` validation — A1 (#198) / A2 (#199) / A3 (#201).

---

## 9. Open Questions

- [ ] None — contract and scope resolved in ADR-018 and the PRD.
