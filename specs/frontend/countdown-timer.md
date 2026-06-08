# Frontend / UI Spec: Profile Countdown Timer

**Status:** Draft
**Author:** Jack Hu
**Last updated:** 2026-06-04
**GitHub issue:** #110
**Affected screens:** Edit/Create Profile, Run (running state)
**Source file(s):** `aquila_web/static/profiles/edit.js`, `aquila_web/static/profiles/edit_form.html`, `aquila_web/static/script.js`, `aquila_web/static/run.html`, `aquila_web/main.py`

---

## 1. Overview

This spec adds an **optional estimated completion time** to run profiles and uses it to drive a **countdown timer** on the Run screen.

- When creating or editing a profile, the operator can optionally enter an estimated completion time (in **minutes**). This is persisted to the profile's JSON file.
- When a run starts, if the selected profile has an estimate set, the Run screen shows a **countdown** (`Time Remaining`) from the estimate toward zero instead of the current count-up stopwatch.
- If the estimate is absent or `null`, the Run screen keeps the **existing elapsed-time stopwatch** behavior exactly as it is today.
- When the countdown reaches zero, it **stops at `00:00`** (it does **not** go negative) and a **"Finishing Run" overlay** appears — modeled on the existing "Stopping Run…" modal — reading **"Finishing Run, Please Wait…"**. This overlay stays up until the run actually completes (or is stopped).
- The machine's runtime is not dictated by the countdown. If the machine finishes a run while the countdown still has time left, the UI switches to the done/complete state exactly as it does today — the countdown is purely informational and never drives run state.
- `time_unavailable` and `estimated_completion_seconds` fields always present in bundled json files and located above steps.
- If `time_unavailable` true, then  `estimated_completion_seconds` should be null. Else, `estimated_completion_seconds` displays the time in seconds.

---

## 2. Screen Inventory

| Screen ID | Name | Entry condition | Exit conditions |
|-----------|------|----------------|-----------------|
| `profile-edit` | Create / Edit Profile | User taps "New Profile" or "Edit" on Profiles page | User taps "Save profile" or "Cancel" |
| `running` | Run — running state | A run is started (`notifyRun()`) and backend reports `screen === "running"` | Run completes (`complete`) or is stopped (`ready`) |

No new screens are introduced. The feature modifies two existing screens.

---

## 3. State Machine Transitions

No state-machine transitions change. The feature only affects:

1. **Profile persistence** — a new optional field on the profile JSON.
2. **Timer rendering** within the existing `running` screen — countdown vs. stopwatch is a *display mode*, not a new state.

```
profiles-page --[New / Edit]--> profile-edit --[Save]--> profiles-page
ready --[notifyRun + backend "running"]--> running   (timer renders countdown OR stopwatch)
running --[backend "complete"]--> complete
running --[Stop Run / backend "ready"]--> ready
```

---

## 4. Screen Designs

### Screen: `profile-edit`

**New field — Estimated completion time:**
- Located in the profile details card (`#profile-edit-details` in `edit_form.html`), in its own field row below Profile name / FAM / ROX.
- Label: **"Est. Time (Min)"**, optional.
- Input: `<input id="profile-estimated-minutes" type="number" inputmode="numeric" min="1" step="1" placeholder="(Optional)" />`, empty by default. The greyed-out **"(Optional)"** placeholder shows when the field is empty and disappears as the operator types.

**Behavior:**
- **Create:** if the field is left blank, the profile is saved with no estimate (`time_unavailable: true`, `estimated_completion_seconds: null`). If a positive number is entered, it is stored (`time_unavailable: false`, seconds = minutes × 60).
- **Edit:** the field is pre-populated from the profile's stored value (converted seconds → minutes). The operator may change it, or clear it to remove the estimate.
- **Read View:** the field lives in the details card, which is hidden in Read View (consistent with Profile name / FAM / ROX); the estimate is not shown separately in the read-only summary.

**Validation (client-side):**
- Blank → no estimate (valid).
- Must be a positive integer if provided. Non-numeric, zero, or negative → show the inline error **"Invalid Estimated Time"** and block the save.
- Decimals: rounded to the nearest whole minute.

### Screen: `running` (timer region)

The timer region is `#running-section` in `run.html`:

```html
<div class="run-timer">
  <span class="run-timer__label" id="run-timer-label">Elapsed Time</span>
  <span class="run-timer__value" id="timer">00:00</span>
</div>
```

**Countdown mode (estimate is set):**
- Label (`#run-timer-label`) reads **"Time Remaining"**.
- Value shows `remaining = estimate_seconds − elapsed`, formatted `M:SS` (or `MM:SS`).
- When `remaining` reaches `0` (i.e. `elapsed >= estimate_seconds`), the value **holds at `00:00`** — it does **not** go negative — and the **"Finishing Run" overlay** (below) is shown. The timer is not used to detect completion; the run only ends when the backend reports `complete`/`ready`.

**Stopwatch mode (estimate absent / null):**
- Label reads **"Elapsed Time"** (unchanged).
- Value shows `elapsed` exactly as today.

**Mode selection:**
- The mode is decided when the `running` screen is entered, based on the **currently selected profile's** estimate.
- The estimate for the active profile is fetched via `/profiles/details?id=<profileId>` (same call already used by `loadProfileLabels()`), and cached for the duration of the run.

**Error states:**
- If the estimate cannot be fetched (network error / profile missing the field), **fall back to stopwatch mode** silently.

### Overlay: "Finishing Run" modal

A new overlay modeled on the existing "Stopping Run…" modal (`#run-stopping-modal`). Added to `run.html` alongside the other run modals:

```html
<div class="run-modal is-hidden" id="run-finishing-modal" role="alertdialog" aria-live="assertive">
  <div class="run-modal__card run-modal__card--finishing">
    <p>Finishing Run, Please Wait…</p>
  </div>
</div>
```

**Trigger:**
- Shown when, in countdown mode, the computed `remaining <= 0` (the estimate has elapsed) **and** the backend still reports `screen === "running"`.
- Only applies in countdown mode — never appears in stopwatch mode.

**Wording:**
- Default: **"Finishing Run, Please Wait…"** (matches the style of "Stopping Run…"). Animated trailing dots optional, mirroring `showRunStoppingModal()`.

**Dismiss / lifecycle:**
- Non-dismissable by the operator (no close button), like the stopping modal.
- Auto-hidden when the backend leaves the `running` screen (`complete` or `ready`), via the same reset path that hides the stopping modal.
- **Precedence:** if the operator presses Stop Run while the finishing overlay is up, the existing "Stopping Run…" flow takes precedence — hide the finishing overlay and show the stopping overlay.

---

## 5. Data Binding

| UI Element | Data Source | Update Trigger |
|------------|-------------|----------------|
| `#profile-estimated-minutes` (load) | `/profiles/details` → `estimated_completion_seconds` (÷ 60) | On profile-edit page load |
| `#profile-estimated-minutes` (save) | POST `/profiles` → `estimated_minutes` (× 60 server-side, or sent as seconds) | On "Save profile" |
| `#timer` (stopwatch mode) | WebSocket `panel.elapsed` | Every WS tick (~1s) |
| `#timer` (countdown mode) | `max(0, cachedEstimateSeconds − panel.elapsed)`, computed client-side | Every WS tick (~1s) |
| `#run-timer-label` | Presence of `cachedEstimateSeconds` for active profile | On entering `running` screen |
| `#run-finishing-modal` | `countdown mode && remaining <= 0 && screen === "running"` | Every WS tick (~1s) |

**Computation detail (frontend, in `script.js`):**
- Reuse the existing `formatElapsed(seconds)` path. Introduce a `countdownSeconds` (nullable) module variable set when a run starts.
- In `wsHandleMessage`, when `"elapsed" in panel`:
  - If `countdownSeconds != null` (countdown mode):
    - `remaining = countdownSeconds - panel.elapsed`.
    - Render `formatRemaining(Math.max(0, remaining))` — the display clamps at `00:00` and never shows a negative value.
    - If `remaining <= 0`, call `showRunFinishingModal()`; otherwise ensure it is hidden.
  - Else (stopwatch mode): render `formatElapsed(panel.elapsed)` (current behavior).
- `formatRemaining(n)` formats a non-negative second count identically to elapsed (`M:SS`).
- `showRunFinishingModal()` / `hideRunFinishingModal()` mirror the existing `showRunStoppingModal()` / `hideRunStoppingModal()` helpers (toggle `is-hidden` on `#run-finishing-modal`, optional animated dots).
- The local `setInterval` that increments `seconds` should remain consistent — countdown display must always derive from authoritative `panel.elapsed`, not the local tick, to avoid drift. (Local tick may be used only for smooth between-message updates if desired.)
- Reset `countdownSeconds` to `null` **and** call `hideRunFinishingModal()` when leaving `running` (screen `ready`/`complete`), mirroring the existing `lastElapsedSeconds = null` / `hideRunStoppingModal()` reset path.
- The finishing overlay must yield to the stopping overlay: when the Stop Run flow runs (`showRunStoppingModal()`), hide the finishing overlay first.

---

## 6. Data Model / JSON Changes

**Profile JSON** always carries two fields, positioned immediately after `rox_unavailable` (or after `title` when `rox_unavailable` is absent):

```jsonc
{
  "output_dir": "pcr_data",
  "post_in_gui": "True",
  "title": "STEC and EPEC",
  "rox_unavailable": true,
  "time_unavailable": false,              // NEW — true when NO estimate is set
  "estimated_completion_seconds": 3900,   // NEW — int seconds when set, else null
  "steps": [ /* ... */ ]
}
```

- **`time_unavailable`** (bool) — mirrors the `rox_unavailable` convention. `true` = no estimate (stopwatch); `false` = estimate set (countdown).
- **`estimated_completion_seconds`** (int seconds, or `null`) — stored in seconds to match step `duration` units and the WebSocket `elapsed` unit, even though the UI input is in minutes. `null` whenever `time_unavailable` is `true`.
- Both keys are **always written** on save (never removed), and both are returned by `/profiles/details`.
- Backend changes (in `aquila_web/main.py`):
  - `ProfileSave` model: `estimated_minutes: Optional[int] = None` (the UI sends minutes; `null` clears the estimate).
  - `estimated_minutes_to_seconds()` helper: converts minutes → whole seconds; returns `None` for blank / non-positive / invalid input (decimals are rounded).
  - `save_profile()`: computes the seconds, then sets `time_unavailable = (seconds is None)` and `estimated_completion_seconds = seconds`. When `estimated_minutes` is omitted by the caller, the existing value is preserved. Both keys are always present.
  - `_order_time_fields()`: positions the two keys right after `rox_unavailable` / `title` before the file is written.
  - `profile_details()`: returns both `time_unavailable` and `estimated_completion_seconds` on **both** return branches (see §10.1 for the bug where the main branch initially missed `time_unavailable`).

---

## 7. Accessibility / Kiosk Constraints

- Touch target minimum size: 44×44px (numeric input + on-screen keyboard already used for other fields).
- The minutes input uses the existing on-screen keyboard (`keyboard.js`) numeric mode.
- No hover states (touch-only).
- "Time Remaining" / "Elapsed Time" label and the timer value must remain readable at kiosk viewing distance (same sizing as current `.run-timer__value`).
- The "Finishing Run" overlay reuses the existing `.run-modal` styling and uses `role="alertdialog"` / `aria-live="assertive"`, consistent with the "Stopping Run…" modal.

---

## 8. Acceptance Criteria

- [ ] Profile editor shows an optional "Est. Time (Min)" field (with `(Optional)` placeholder) on both create and edit.
- [ ] Saving a profile with a positive value writes `estimated_completion_seconds` (= minutes × 60) and `time_unavailable: false` to the profile JSON.
- [ ] Saving with the field blank stores `time_unavailable: true` / `estimated_completion_seconds: null`, and editing can clear a previously set estimate.
- [ ] An invalid entry (zero / negative / non-numeric) shows "Invalid Estimated Time" and blocks the save.
- [ ] On Run, if the selected profile has an estimate, the timer label reads "Time Remaining" and counts down from the estimate.
- [ ] On Run, if the profile has no estimate, the timer behaves exactly as the current elapsed stopwatch ("Elapsed Time").
- [ ] When the countdown reaches zero, the timer holds at `00:00` (never negative) and the "Finishing Run, Please Wait…" overlay appears while the backend still reports `running`.
- [ ] The finishing overlay auto-hides when the run completes or is stopped, and never appears in stopwatch mode.

---

## 9. Test Plan

Tests are layered to match the marker convention in `pytest.ini` (`unit`, `contract`, `e2e`). The backend/data-model behavior is covered by automated tests; the live, timing-dependent timer UI is covered by a manual dev checklist.

### 9.1 Unit tests — `unit_tests/test_estimated_completion.py` (`unit`)

Pure backend logic, no hardware/network.

- **`estimated_minutes_to_seconds()`**
  - Positive minutes convert to seconds (×60): `1→60`, `45→2700`, `90→5400`.
  - Invalid/blank input returns `None` (→ no estimate): `None`, `0`, negatives, `""`, non-numeric strings, `NaN`, `±inf`, booleans.
  - Decimal minutes round to the nearest whole minute (`2.4→120`, `2.6→180`).
- **`_order_time_fields()`**
  - `time_unavailable` + `estimated_completion_seconds` are inserted immediately after `rox_unavailable` when present, otherwise after `title`, and always before `steps`.
  - Existing values and all other keys are preserved.
  - Idempotent: re-running produces identical output.

### 9.2 Contract tests — `tests/contract/test_profile_endpoints.py` (`contract`)

FastAPI `TestClient`, exercising `/profiles` + `/profiles/details`.

- Create with `estimated_minutes=45` → details returns `estimated_completion_seconds=2700` and `time_unavailable=false`.
- Create with no estimate → `estimated_completion_seconds=null` and `time_unavailable=true`.
- Edit with `estimated_minutes=null` clears the estimate → `null` / `time_unavailable=true`.
- Edit omitting the field preserves the existing estimate (no accidental wipe).
- Saved JSON on disk always carries **both** keys, positioned right after `rox_unavailable`/`title` (verifies lines 21–22).

### 9.3 E2E DOM tests — `tests/e2e/test_countdown_timer.py` (`e2e`)

Playwright against a running frontend (page-load only, no sim run required).

- `#run-finishing-modal` exists, is hidden by default, and contains "Finishing Run".
- `#run-timer-label` element is present on the Run screen.
- `#profile-estimated-minutes` exists on the edit form with placeholder `(Optional)`.

### 9.4 Manual dev checklist (live timer UI)

Run dev with `AQ_DEV_SIMULATE=1` and `AQ_DEV_RUN_DURATION=90`:

- [ ] Profile **with** estimate → on Run, label reads **"Time Remaining"** and counts down.
- [ ] Estimate shorter than run duration → at `00:00` the timer **holds** (no negative) and **"Finishing Run, Please Wait…"** appears.
- [ ] Profile **without** estimate → label **"Elapsed Time"**, counts up; finishing flag never shows.
- [ ] Finishing flag **auto-hides** on complete/ready.
- [ ] Pressing **Stop Run** while the finishing flag is up → **"Stopping Run…"** takes precedence.

---

## 10. Bugs Found During Testing

### 10.1 `profile_details()` omitted `time_unavailable` on the main response branch

**Found by:** the contract tests in §9.2 (`test_create_with_estimate_persists_seconds_and_flag`, `test_create_without_estimate_is_time_unavailable`, `test_edit_clears_estimate_when_minutes_null`, `test_edit_omitting_estimate_preserves_existing`), which failed with `KeyError: 'time_unavailable'`.

**Symptom:** `save_profile()` correctly wrote both `time_unavailable` and `estimated_completion_seconds` to the JSON file (the on-disk shape test passed), but `GET /profiles/details` did not return `time_unavailable` for normal profiles. The field was present only in the legacy `configuration`-style return branch, not in the main branch that ordinary profiles use — so any consumer reading the API response saw an incomplete payload.

**Impact:** Low for the countdown feature itself (the Run screen and editor key off `estimated_completion_seconds`, which was still returned), but the response did not match the spec's data model — `time_unavailable` should always be exposed. It would bite any future consumer that relied on the boolean.

**Root cause:** `profile_details()` has two return paths. When the `time_*` fields were added, only the legacy branch received `time_unavailable`; the main branch was missed.

**Fix:** Added the field to the main return branch in `aquila_web/main.py`, with the same sensible default as the legacy branch (`true` when there is no estimate):

```python
"time_unavailable": bool(data.get("time_unavailable", data.get("estimated_completion_seconds") is None)),
```

**Verification:** All four failing contract tests now pass; full unit + contract run is green (33 passed).

