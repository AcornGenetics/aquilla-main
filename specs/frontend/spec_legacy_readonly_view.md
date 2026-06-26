# Frontend / UI Spec: Legacy Read-only View — lock, summary header, aligned layout, no flash (issue #211)

**Status:** Active
**Author:** Aquila Engineering Team
**Last updated:** 2026-06-26
**GitHub issue:** #211 (Structured Profiles B4)
**Affected screens:** Legacy Profile read-only view (`/profiles/edit-form?id=<id>&view=1`)
**Source file(s):** `aquila_web/static/profiles/edit_form.html`, `aquila_web/static/profiles/edit.js`, `aquila_web/static/styles.css`, `tests/e2e/`
**Umbrella PRD:** `specs/prd/structured-profile-editor-prd.md` · **Decision:** ADR-018
**Depends on:** #203 (B3 routes Legacy Profiles to `?view=1` and made `edit.js` honour read-only) — merged.

---

## 1. Overview

B3 routes Legacy Profiles to the existing viewer (`edit_form.html` / `edit.js`) via `?view=1` and made the param actually open read-only. B4 makes that viewer **truly read-only and presentable**, in four parts:

1. **Lock it** — no "Edit View" toggle in read-only mode, so a Legacy Profile has no in-app path back to editing.
2. **Summary header** — name, FAM/ROX labels, and estimated minutes (when set) at the top of the read view.
3. **Aligned step layout** — fix the field-count-driven zig-zag so steps line up.
4. **No flash** — the read-only view renders from first paint; the editable editor never flashes.

Out of scope: any change to the structured builder; re-deriving Legacy `steps`; the integration convergence (C / #204, which has been told about these changes).

Context: plain HTML/CSS/JS, no build step (ADR-003); 768×1024 Pi kiosk (ADR-005). The viewer is reached only from the Profiles list's Legacy "View" affordance (B3).

---

## 2. Screen Inventory

| Screen ID | Name | Entry condition | Exit conditions |
|-----------|------|----------------|-----------------|
| `legacy-view` | Profile Details (read-only) | `/profiles/edit-form?id=<id>&view=1` (Legacy row "View") | Back ‹ → Profiles list |
| `legacy-edit` | Edit Run Profile (unchanged) | `/profiles/edit-form?id=<id>` (no `view` param) | Save / Cancel |

`?view=1` ⇒ `legacy-view` (locked); no param ⇒ `legacy-edit` (editable, toggle present — unchanged).

---

## 3. Behaviour

### 3.1 Lock the read-only view (no escape hatch)

- In read-only mode the **"Edit View" toggle (`#toggle-read-view`) is not shown** — there is no control to flip a Legacy Profile into the editable legacy editor.
- The toggle remains present and functional in normal edit-mode entry (no `view` param).

### 3.2 Summary header

At the top of the Profile Summary (read view), above the per-stage step list, render a header block showing:
- **Profile name**
- **FAM** label and **ROX** label (the values entered on the Profile)
- **Estimated time (minutes)** — shown **only when an estimate is set**; the row is omitted entirely when there is no estimate.

Values come from the already-loaded Profile (the same data `edit.js` populates into the form fields). The estimate is present iff `estimated_completion_seconds` is a positive number (→ minutes).

### 3.3 Aligned step layout

The summary step rows currently use `grid-template-columns: repeat(auto-fit, minmax(120px, 1fr))`, so a row's column count tracks its field count (setpoint ≈ 5 fields, ramp/enable ≈ 3–4) and the columns don't line up across rows — the zig-zag. Replace with a **fixed column grid** (every step row uses the same column tracks regardless of how many fields it has), so labels/values align top-to-bottom. Rows with fewer fields simply leave trailing tracks empty.

### 3.4 No flash of the editable view

Today `edit_form.html` paints the editable form first; `edit.js` then runs `applyViewMode()` and hides the edit sections — a brief flash of the editor. The read-only state must be applied **before first paint**:
- A tiny synchronous script (in `<head>`/top of `<body>`) reads the `view`/`mode` param and adds a `view-only` class to `<html>` before the body renders.
- CSS keyed on `html.view-only` immediately hides the editable sections (`.profile-edit`) and the toggle, and reveals `#profile-summary` — so the editor never paints.
- `edit.js`'s existing `applyViewMode()` still runs (it populates the summary and disables inputs); the pre-paint CSS only removes the visual flash. The two must agree (same end state).

---

## 4. Data Binding

| UI element | Source | Trigger |
|------------|--------|---------|
| Summary header: name / FAM / ROX | loaded Profile (`title`, `labels.fam`, `labels.rox`) | On read-view render |
| Summary header: est. minutes (if set) | `estimated_completion_seconds` → minutes | On read-view render; omitted when unset |
| Editable vs read-only at first paint | `?view=1` / `?mode=view` → `html.view-only` | Synchronously before paint |

---

## 5. Accessibility / Kiosk Constraints

- Read view is for inspection only — no editable affordances, no toggle.
- Summary remains legible on the 768×1024 kiosk; aligned columns improve scanability.

---

## 6. Acceptance Criteria

- [ ] Entering a Legacy Profile (`?view=1`) shows **no "Edit View" toggle**; no in-app path from read view to editing.
- [ ] The read view shows **name + FAM + ROX** at the top of the summary; the **estimated-minutes row appears only when an estimate is set** and is absent otherwise.
- [ ] Step rows are **column-aligned** (no zig-zag) whether a row has 2 or 5 fields.
- [ ] Clicking **View** lands directly on the read-only view with **no momentary flash** of the editable editor (read-only applied before first paint).
- [ ] Normal (non-`view`) edit entry is **unchanged** — toggle present, sections editable.
- [ ] e2e tests in `tests/e2e/` for the locked view, the summary header (estimate present/absent), the aligned layout, and the no-flash behaviour.

---

## 7. Out of Scope (other issues)

- Structured builder, validation, round-trip, list routing — B1–B3 (#200/#202/#203), merged.
- Integration convergence and PR to `main` — C (#204), updated to expect this viewer's new behaviour.
- Re-authoring the legacy step editor itself (edit mode) — only the read-only presentation changes here.

---

## 8. Open Questions

- [ ] None — scope and decisions resolved in #211 and ADR-018.
