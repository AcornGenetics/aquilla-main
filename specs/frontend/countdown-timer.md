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
- Located in the profile details card (`#profile-edit-details` in `edit_form.html`), alongside Profile name / FAM / ROX.
- Label: **"Estimated completion time (minutes)"**, optional.
- Input: `<input id="profile-estimated-minutes" type="number" inputmode="numeric" min="1" step="1" />`, empty by default.
- Helper text: "Optional. If set, the Run screen shows a countdown instead of an elapsed-time stopwatch."

**Behavior:**
- **Create:** if the field is left blank, the profile is saved with no estimate (field `null` / omitted). If a positive number is entered, it is stored.
- **Edit:** the field is pre-populated from the profile's stored value (converted seconds → minutes). The operator may change it, or clear it to remove the estimate.
- **Read View:** the estimate is shown as a read-only summary row ("Estimated completion: N min") only when set.

**Validation (client-side):**
- Blank → no estimate (valid).
- Must be a positive integer if provided. Non-numeric, zero, or negative → treat as no estimate / show inline validation message "Enter a positive number of minutes."
- Decimals: round to the nearest whole minute (or reject — see Open Questions).

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

**Profile JSON** gains one optional top-level field:

```jsonc
{
  "output_dir": "pcr_data",
  "post_in_gui": "True",
  "title": "Verification Profile",
  "labels": { "fam": "FAM", "rox": "ROX" },
  "estimated_completion_seconds": 2700,   // NEW — optional; 45 min. null or absent => stopwatch
  "steps": [ /* ... */ ]
}
```

- **Field name:** `estimated_completion_seconds` (integer seconds). Stored in seconds to match step `duration` units and the WebSocket `elapsed` unit, even though the UI input is in minutes.
- **Absent or `null`** → stopwatch behavior (current).
- Backend changes (in `aquila_web/main.py`):
  - `ProfileSave` model: add `estimated_minutes: Optional[int] = None` (or `estimated_completion_seconds`).
  - `save_profile()`: when present and positive, set `base_profile["estimated_completion_seconds"] = minutes * 60`; when explicitly blank/`null`, remove the key (so editing can clear it). Preserve the value on edits when the field is omitted vs. explicitly cleared — see Open Questions.
  - `profile_details()`: include `"estimated_completion_seconds": data.get("estimated_completion_seconds")` in the response payload so the frontend (edit form + run screen) can read it.

---

## 7. Accessibility / Kiosk Constraints

- Touch target minimum size: 44×44px (numeric input + on-screen keyboard already used for other fields).
- The minutes input uses the existing on-screen keyboard (`keyboard.js`) numeric mode.
- No hover states (touch-only).
- "Time Remaining" / "Elapsed Time" label and the timer value must remain readable at kiosk viewing distance (same sizing as current `.run-timer__value`).
- The "Finishing Run" overlay reuses the existing `.run-modal` styling and uses `role="alertdialog"` / `aria-live="assertive"`, consistent with the "Stopping Run…" modal.

---

## 8. Acceptance Criteria

- [ ] Profile editor shows an optional "Estimated completion time (minutes)" field on both create and edit.
- [ ] Saving a profile with a positive value writes `estimated_completion_seconds` (= minutes × 60) to the profile JSON.
- [ ] Saving with the field blank stores no estimate (key absent / `null`), and editing can clear a previously set estimate.
- [ ] On Run, if the selected profile has an estimate, the timer label reads "Time Remaining" and counts down from the estimate.
- [ ] On Run, if the profile has no estimate, the timer behaves exactly as the current elapsed stopwatch ("Elapsed Time").
- [ ] When the countdown reaches zero, the timer holds at `00:00` (never negative) and the "Finishing Run, Please Wait…" overlay appears while the backend still reports `running`.
- [ ] The finishing overlay auto-hides when the run completes or is stopped, and never appears in stopwatch mode.

---

