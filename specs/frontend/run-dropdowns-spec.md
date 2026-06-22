# Frontend / UI Spec: Run Page Dropdowns — Custom Themed Pickers & Run-Name Autofill Suppression

**Status:** Active
**Author:** Rasita Vajapattana
**Last updated:** 2026-06-16
**GitHub PR:** #170
**Affected screens:** `run` (ready section)
**Source file(s):** `aquila_web/static/run.html`, `aquila_web/static/script.js`, `aquila_web/static/styles.css`, `aquila_web/main.py`

---

## 1. Overview

Replaces the browser-native form controls in the Run card with app-controlled UI so appearance is **consistent across browsers and machines** (kiosk requirement). Three related changes:

1. **Profile dropdown** — the native `<select>` profile picker is replaced by a custom, themed dropdown (button + listbox). The open option list is styled by the app instead of the OS, matching the rest of the page.
2. **Optics-path dropdown** (dev mode only) — the plain text input gains a custom autocomplete dropdown backed by **server-stored** recent-path history, replacing the browser's per-machine autofill.
3. **Run-name autofill suppression** — the Run Name input no longer shows the browser's native "recent values" dropdown.

No change to run execution logic; the native `<select>` is retained (hidden) as the source of truth so all existing reads (`value`, `selectedOptions`) keep working. This cosmetic-overlay-over-native-control approach is recorded in **ADR-012**.

> **Scope note:** Items 1 and 3 (Profile dropdown + Run-name autofill suppression) satisfy issue **#166**. Item 2 (the Optics-path dropdown) is **beyond #166's stated acceptance criteria** but ships in the same PR (#170) because it is the same screen and the same theming pass; it is documented here rather than split into a separate issue.

**Implementation shape:** the two controls are built as **two bespoke functions** (`setupProfileCombo`, `setupOpticsCombo`) sharing only CSS theme tokens and minimal-to-no JS — not a generic widget (there is no pre-existing custom dropdown component to reuse; `keyboard.js` is the only custom widget and is unrelated). Both combos are **force-closed when the screen leaves `ready`** (hooked into the screen-render path in `script.js`, alongside the `#ready-section` `is-hidden` toggle) so they never re-enter `ready` in a stale-open state with a dangling outside-click listener.

---

## 2. Screen Inventory

| Screen ID | Name | Entry condition | Exit conditions |
|-----------|------|----------------|-----------------|
| `run` (ready) | Ready to Run | Hardware ready, idle | Operator taps **Run** → `running` |

> All three controls live in the `#ready-section` of the Run page. The optics field (`#run-optics-tab`) is only visible when `dev_simulate` is true.

---

## 3. State Machine Transitions

```
Profile dropdown:
[closed] --click button-->        [open]    (custom listbox shown)
[open]   --pick option-->         [closed]  (label updates; native <select> change dispatched → /profile/select)
[open]   --click outside / Esc--> [closed]  (no change)

Optics dropdown (dev only):
[closed] --focus / type-->        [open]    (history filtered as you type)
[open]   --pick / Enter-->        [closed]  (input set; POST /dev/optics_path; history updated)
[open]   --blur / Esc / outside-->[closed]  (blur also saves current value)
```

Driven by `setupProfileCombo` / `renderProfileCombo` / `syncProfileComboLabel` and `setupOpticsCombo` in `aquila_web/static/script.js`.

---

## 4. Screen Designs

### Region: Profile picker (`.profile-combo`)

**Layout:**
- Hidden native `<select id="mySelect">` (source of truth, `display:none`).
- `<button id="profile-combo-button">` styled with `.run-profile-select` (same box as before) — shows selected profile label + rotating chevron.
- `<ul id="profile-combo-list" role="listbox">` — themed option list, absolutely positioned below the button.

**Dynamic content:**
- Options mirror the native select's `<option>`s (placeholder skipped).
- Button label = selected option text, or "Select a profile" when none chosen.

**User interactions:** Click button to open/close; click option to select; `ArrowDown` opens; `Esc` closes; outside click closes.

**Error states:** Empty profile list → native select shows "No profiles found"; custom list renders empty.

### Region: Optics path picker (`.optics-combo`, dev only)

**Layout:**
- `<input id="dev-optics-path" autocomplete="off" role="combobox" class="keyboard-ignore">` inside `.optics-combo`. The `keyboard-ignore` class excludes it from the on-screen keyboard (`keyboard.js`), since Optics is dev-only and used with a physical keyboard — the on-screen keyboard would otherwise cover the suggestion list.
- `<ul id="optics-suggestions" role="listbox">` — themed suggestion list.

**Dynamic content:**
- Suggestions = server history filtered (case-insensitive substring) by current input text.

**User interactions:** Focus shows full history; typing filters; `ArrowUp/Down` navigate; `Enter` selects active; `Esc`/outside-click/blur close; blur saves current text.

**Error states:** No matching history → list hidden; free-typed new paths are allowed and saved.

### Region: Run Name input (`#run-name-input`)

**Layout:** Unchanged text input; adds `autocomplete="off"`.

**User interactions:** No suggestion dropdown is offered by the browser.

---

## 5. Data Binding

| UI Element | Data Source | Update Trigger |
|------------|-------------|----------------|
| `#profile-combo-label` | `#mySelect` selected option text (DOM) | On select / preselection (`syncProfileComboLabel`) |
| `#profile-combo-list` options | `#mySelect` `<option>`s (DOM) | After `loadProfiles` populates select |
| Profile selection | `POST /profile/select` | Custom option click → dispatched native `change` |
| `#dev-optics-path` value | `GET /dev/optics_path` → `path` | On dev-mode init |
| `#optics-suggestions` items | `GET /dev/optics_path` → `history[]` | On init + after each `POST /dev/optics_path` |
| Optics path persistence | `POST /dev/optics_path` | On suggestion select / input blur |

---

## 6. Backend Contract

`GET /dev/optics_path` → `{ "path": str|null, "history": string[] }`
`POST /dev/optics_path` body `{ "path": str }` → `{ "path": str|null, "history": string[] }`

History rules — the transformation is a **pure function** (`_merge_optics_history(history, path) -> history` in `aquila_web/main.py`), with persistence and selection layered separately so the rules are testable without a backend, a file, or HTTP:
- Most-recent-first ordering.
- De-duplicated (re-entering a path moves it to the front).
- Capped at `OPTICS_PATHS_LIMIT = 20`; older entries dropped.
- Blank/whitespace path returns history **unchanged** (the pure function never models "clear").

Layered around the pure function:
- **Persistence**: thin load/save wrappers read/write `logs/optics_paths.json` (gitignored, per-server). Not part of the pure function.
- **Selection**: blank/whitespace path clears the current selection (`dev_optics_path = None`) at the endpoint level — a separate concern from history, which it never touches.

The endpoint is therefore `history = _merge_optics_history(load().history, path); save(...)`.

---

## 7. Accessibility / Kiosk Constraints

- Consistent appearance across browsers/machines is the primary driver (kiosk units must look identical).
- Profile button reuses `.run-profile-select` sizing (20px). Option list 18px; optics suggestions 14px (matches optics input).
- ARIA: profile button `aria-haspopup="listbox"` / `aria-expanded`; lists use `role="listbox"` / `role="option"`; optics input `role="combobox"` / `aria-autocomplete="list"`.
- Themed via existing tokens: `#e2e8f0` border, 16px radius, `rgba(15,23,42,0.08)` shadow, `#f8fafc` hover.

---

## 8. Assets

| Asset | Path | Format | Notes |
|-------|------|--------|-------|
| — | — | — | No new assets; CSS/markup/JS + one backend endpoint change |

---

## 9. Acceptance Criteria

- [ ] Profile picker open list is app-styled and identical across browsers/machines.
- [ ] Selecting a profile from the custom list still POSTs to `/profile/select` and loads dye labels (no regression).
- [ ] Profile preselection (URL `?profile=` and `/button_status`) updates the custom button label.
- [ ] Optics field (dev mode) shows a themed dropdown of recent paths, filtering as you type.
- [ ] Optics history is server-stored, most-recent-first, deduped, capped at 20, and survives reload.
- [ ] Run Name input no longer shows the browser's native autofill dropdown.
- [ ] All three controls visually match the rest of the application theme.

---

## 10. Testing

Coverage maps onto the three existing layers (no JS unit harness — ADR-003 keeps Node out of the project):

| What | Layer | Location |
|------|-------|----------|
| Profile listbox: open / select / Esc / outside-click, label sync, native `change` still fires | Playwright e2e | `tests/e2e/test_run_dropdowns.py` |
| Profile + Optics combos force-closed after leaving `ready` (open → run start → complete → assert closed) | Playwright e2e | same file |
| Optics typeahead: filter-as-you-type, Arrow/Enter/Esc, blur-saves, outside-click | Playwright e2e | same file |
| Run Name input has `autocomplete="off"` | Playwright e2e (attribute assertion) | same file |
| `GET`/`POST /dev/optics_path` wiring (POST path → appears in GET `history`; POST blank → `path` null, history intact) | contract (httpx) | `tests/contract/test_optics_path_endpoints.py` |
| History rules (most-recent-first, dedupe-moves-to-front, cap-at-20, blank/whitespace returns input unchanged) | pure unit | `unit_tests/test_optics_history.py` (calls `_merge_optics_history` directly) |

> DOM-behavior (e2e) coverage **skip-gates on a live backend**, matching the existing `tests/e2e/test_keyboard.py` convention. In bare CI, `pytest tests unit_tests -v` exercises the contract + pure-unit tests for real; the e2e tests skip unless a backend is reachable at `AQUILA_TEST_URL`.

---

## 11. Open Questions

- "Consistent across all machines" currently means consistent **appearance**; the optics history is stored per server instance (`logs/optics_paths.json`). If the same history must be shared across physically separate devices, a shared/synced store is required.
- Some browsers ignore `autocomplete="off"` on name-like fields; if native suggestions reappear, switch the Run Name input to `autocomplete="new-password"`.
