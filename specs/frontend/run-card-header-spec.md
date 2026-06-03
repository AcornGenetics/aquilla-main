# Frontend / UI Spec: Run Card Header — Live Profile & Run Name

**Status:** Active
**Author:** Jack Hu
**Last updated:** 2026-06-02
**GitHub issue:** #93
**Affected screens:** `ready`, `running`, `complete`
**Source file(s):** `aquila_web/static/run.html`, `aquila_web/static/script.js`, `aquila_web/static/styles.css`

---

## 1. Overview

Replaces the static **"Start Run"** heading in the top-left corner of the Run Start card. The heading is removed entirely; the user never sees "Start Run". Instead, once a run begins, that corner displays the **selected profile name** (top line) and the **run name** (line below), so the operator can confirm what's running while the input controls are hidden.

---

## 2. Screen Inventory

| Screen ID | Name | Entry condition | Exit conditions |
|-----------|------|----------------|-----------------|
| `ready` | Ready to Run | Hardware ready, idle | Operator taps **Run** → `running` |
| `running` | Run In Progress | `/button/run` accepted | Run completes → `complete`; **Stop** → `ready` |
| `complete` | Results | Run finished | New run / acknowledge → `ready` |

> The card header content changes per screen; the card element is not itself toggled.

---

## 3. State Machine Transitions

```
[ready]    --tap Run-->            [running]   (header corner fills: profile + run name)
[running]  --run finishes-->       [complete]  (header corner stays filled)
[complete] --new run / ready-->    [ready]     (header corner clears to empty)
```

Driven by `updateStartHeader(screen)` in `aquila_web/static/script.js`, called from `updateDashboardSections`.

---

## 4. Screen Designs

### Region: Run Start card header (`.run-start-header`)

**Layout:**
- Left (`.run-start-title`): summary block (`#run-start-summary`) — `#run-start-profile` over `#run-start-runname`. Hidden on `ready`.

**Dynamic content:**
- Profile: `textContent` of the selected `<option>` in `#mySelect` (display name, not raw ID).
- Run name: current value of `#run-name-input`.
- Both read client-side at screen-change time — no new backend endpoint.

**User interactions:** None added.

**Error states:**
- If no profile/name is resolvable, the corresponding line renders empty.

---

## 5. Data Binding

| UI Element | Data Source | Update Trigger |
|------------|-------------|----------------|
| `#run-start-profile` | `#mySelect` selected option text (DOM) | Screen → `running`/`complete` |
| `#run-start-runname` | `#run-name-input` value (DOM) | Screen → `running`/`complete` |
| Summary visibility | `screen === "running" \|\| screen === "complete"` | Each WebSocket `screen` message |

---

## 6. Accessibility / Kiosk Constraints

- Display only — no new touch targets, no virtual keyboard interaction.
- Profile 20px bold; run name 18px bold (matches Ready pill / Reset button font size).
- Profile name vertically aligned with the Ready pill

---

## 7. Assets

| Asset | Path | Format | Notes |
|-------|------|--------|-------|
| — | — | — | No new assets; CSS/markup only |

---

## 8. Acceptance Criteria

- [ ] Remove the “Start Run” text label from the center run button while a run is active
- [ ] On `ready`/`init`, the header corner is empty.
- [ ] Display the selected profile name and run name in the area where “Start Run” previously appeared
- [ ] Ensure the profile/run information matches the styling and formatting used throughout the rest of the application
- [ ] Keep the active run state visually cleaner and less cluttered during execution

---

## 9. Open Questions

