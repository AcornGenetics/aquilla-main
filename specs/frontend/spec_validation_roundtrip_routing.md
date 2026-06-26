# Frontend / UI Spec: Validation UX + Edit Round-trip + List Routing (issue #203)

**Status:** Active
**Author:** Aquila Engineering Team
**Last updated:** 2026-06-26
**GitHub issue:** #203 (Structured Profiles B3)
**Affected screens:** Create/Edit Profile (`/profiles/builder`), Profiles list (`/profiles-page`)
**Source file(s):** `aquila_web/static/profiles/builder.html`, `aquila_web/static/profiles/builder.js`, `aquila_web/static/profiles/profiles.js`, `aquila_web/static/profiles/index.html`, `aquila_web/static/styles.css`, `tests/e2e/test_profile_builder.py`
**Umbrella PRD:** `specs/prd/structured-profile-editor-prd.md` · **Decision:** ADR-018, ADR-003 (plain HTML/JS, no build)
**Depends on:** #200 (builder shell), #202 (Sub-stages), #201 (A3 — endpoints now validate, assemble `steps`, and return the `structured` flag) — all merged into `updated-profiles`.

---

## 1. Overview

B3 is the final frontend slice: it makes the structured builder **trustworthy** (can't save an invalid program), **complete** (can edit existing profiles, not just create), and **wired into the app** (the Profiles list and the New button send each profile to the right editor). It builds against the real merged backend (A3), not a stub.

Three capabilities:
1. **Validation on save** — client-side, mirroring the server's `validate_stages` ranges so a client-valid form never trips the server 400 (which remains the safety net).
2. **Edit round-trip** — opening a structured Profile repopulates every Stage/Sub-stage/value from its `stages` object; saving updates that profile in place.
3. **List routing** — structured Profiles → the builder; Legacy → the existing read-only view; bundled stay read-only. "New profile" → the builder.

Out of scope: changing the assembled `steps`, ranges, or any backend logic (A-side, done); the Legacy editor's internals.

Context: plain HTML/CSS/JS, no build step (ADR-003); 768×1024 Pi kiosk (ADR-005).

---

## 2. Screen Inventory

| Screen ID | Name | Entry condition | Exit conditions |
|-----------|------|----------------|-----------------|
| `builder-new` | Create Profile | `/profiles/builder` (from "New profile") | Valid Save → list; Cancel → list |
| `builder-edit` | Edit Profile | `/profiles/builder?id=<id>` (from a structured row's "Edit") | Valid Save → list; Cancel → list |
| `legacy-view` | View Profile (read-only) | `/profiles/edit-form?id=<id>&view=1` (from a Legacy row's "View") | Back → list |

---

## 3. State Machine Transitions

```
profiles-page --[New profile]----------------> builder-new
profiles-page --[structured row · Edit]-------> builder-edit
profiles-page --[legacy row · View]-----------> legacy-view (read-only)
builder-* --[Save · all enabled fields valid]-> profiles-page
builder-* --[Save · any invalid]--------------> builder-* (errors shown, no navigation)
```

---

## 4. Screen Designs

### 4.1 Validation on save (`builder-*`)

Each validatable numeric field (Stage temp/time, each Sub-stage temp/time, cycles) gets an adjacent error element `<p class="field-error is-hidden">Invalid Value</p>` and, when invalid, the input gets an `is-invalid` red-border class.

**Trigger:** validation runs **only on Save attempt** — never on initial load, so a pristine blank form shows no errors (PRD story 28).

**On Save:**
- Validate every field in **enabled** Stages plus Amplification (always enabled). **Disabled (unchecked) Stages are skipped entirely** — their blanks never block save.
- A field is invalid if blank, non-numeric, or out of range. Ranges (mirroring `validate_stages`):
  - temp: **25–100** °C
  - time: **1–600** s
  - **last (extension-bearing) Sub-stage** time: **11–600** s — the last Sub-stage row, i.e. "Annealing & Extension" (2-step) or "Extension" (3-step)
  - cycles: integer **1–50**
- **All** offending fields flag at once (red border + "Invalid Value"); the first invalid field scrolls into view.
- If anything is invalid: **do not POST, do not navigate**.
- If all valid: clear any error styling and POST as today (B1/B2). The server still re-validates; a 400 `{detail:{errors:[…]}}` surfaces in `#save-status` (defense in depth — should not normally happen given client parity).

**Est. Time (Min):** the optional estimate field is validated on save exactly like the legacy editor (`edit.js`) — blank is fine; a value must be a positive integer, else the field flags `is-invalid` with its "Invalid Estimated Time" message (`#profile-estimated-error`) and blocks the save.

### 4.2 Edit round-trip (`builder-edit`)

On load, if the URL carries `?id=<id>` (or `?profile=`):
- `GET /profiles/details?id=<id>`; read the returned `stages` object.
- Repopulate: `#profile-name` (title), FAM/ROX labels, estimated minutes; each optional Stage's checkbox (`enabled`) + temp/time (triggering the B1 grey/disable sync); Amplification `cycles`; and the Sub-stages — **including adding the third row** when `subStages.length === 3` (reusing B2's add path so names/X/controls are correct), then filling each temp/time.
- Title affordance: the header reads "Edit Profile" in edit mode (vs "Create Profile" for new).
- **Save updates in place:** the payload includes `profile_id: <id>` so the backend overwrites the existing profile rather than creating a copy. (`save_profile` already keys off `profile_id`.)
- A profile with no `stages` should not normally reach here (the list routes Legacy → the read-only view); if `?id` resolves to one, fall back gracefully (leave the form at its blank defaults).

### 4.3 List routing (`profiles.js`)

Replace the single "Edit → `/profiles/edit-form`" affordance with per-row routing keyed on the `structured` and `bundled` flags from `GET /profiles`:

| Row type | Flag | Affordance | Target |
|----------|------|-----------|--------|
| Structured | `structured === true`, not bundled | **Edit** | `/profiles/builder?id=<id>` |
| Legacy | `structured` falsy, not bundled | **View** | `/profiles/edit-form?id=<id>&view=1` |
| Bundled | `bundled === true` | read-only (unchanged — lock icon, no edit affordance) | — |

"New profile" (`index.html`) → `/profiles/builder`.

**`edit.js` read-only fix:** `?view=1` previously got reset back to editable whenever the "Edit View" toggle existed, so the legacy viewer opened editable. That reset is removed so `?view=1` honours read-only. (Fully locking the viewer + the summary header + aligned step layout are **B4 / #211**, deliberately deferred — this issue only guarantees Legacy *opens* read-only.)

---

## 5. Data Binding

| UI element | Source | Trigger |
|------------|--------|---------|
| Builder fields (edit mode) | `GET /profiles/details?id=` → `stages`, title, labels, `estimated_completion_seconds` | On load when `?id` present |
| Row Edit/View affordance | `GET /profiles` → `structured`, `bundled` | On list render |
| Save (create) | `POST /profiles` `{name, fam_label, rox_label, estimated_minutes, stages}` | Save, all valid |
| Save (edit) | as above **plus** `profile_id` | Save, all valid, `?id` present |

Client validation ranges must equal `aquila_web/profile_assembly.py::validate_stages`. If those constants change server-side, the client values here must change too (documented coupling).

---

## 6. Accessibility / Kiosk Constraints

- Error state must be unmistakable on the kiosk: red border **and** the "Invalid Value" text (not colour alone).
- No new tap targets below 44px; existing controls unchanged.

---

## 7. Acceptance Criteria

- [ ] Save with blanks/invalid flags **every** offending enabled field red with "Invalid Value" and does **not** navigate.
- [ ] A pristine blank form shows no errors until a Save is attempted.
- [ ] Disabled Stages never block save (their blank/invalid fields are skipped).
- [ ] The last Sub-stage enforces the 11 s minimum; other times enforce 1 s.
- [ ] Opening a structured Profile (`?id`) repopulates all Stages, Sub-stages (incl. a 3rd when present), and values from `stages`; Save updates it in place (`profile_id`).
- [ ] Profiles list routes structured → builder (Edit), Legacy → read-only view (View); bundled stay read-only.
- [ ] "New profile" opens the builder.
- [ ] e2e tests in `tests/e2e/` for validation display, round-trip repopulation, and list routing; existing B1/B2 tests still pass.

---

## 8. Out of Scope (other issues)

- Backend assembly/validation/ranges and the `structured` flag — A1/A2/A3 (#198/#199/#201), merged.
- The integration issue's real-backend convergence checklist — C (#204).
- Re-authoring the Legacy read-only viewer — it is reused as-is via `?view=1`.

---

## 9. Open Questions

- [ ] None — backend contract is merged (A3) and routing/validation decisions are resolved in ADR-018 and the PRD.
