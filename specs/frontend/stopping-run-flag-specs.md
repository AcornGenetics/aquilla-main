# Frontend / UI Spec: [Screen or Flow Name]

**Status:** Draft
**Author:** Jack
**Last updated:** 2026-06-02
**GitHub issue:** #94
**Affected screens:** `running` 
**Source file(s):** `sentri_web/static/run.html`, `sentri_web/static/script.js`, `sentri_web/static/styles.css`

---

## 1. Overview

When the "Stop Run" button is clicked by the user, it was difficult for the user to identify if the machine was in the process of stopping.

A stopping-run-flag is implemented to indicate to the user that the machine is in the process of stopping its run.

---

## 2. Screen Inventory

The Stopping Run flag only affects one screen state — `running` (reported via the WebSocket `panel.screen` field, defined in `sentri_web/main.py`). No new screen is added.

| Screen ID | Name    | Entry condition                                                   | Exit conditions                                                                                                      |
| --------- | ------- | ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `running` | Running | Run started (`/button/run` with valid profile/name/drawer closed) | Run finishes → `complete`; **Stop Run** pressed → `ready` once the machine has stopped; optics file missing → `ready` |

**Overlay (not a screen):** the **Stopping Run** flag is a modal (`#run-stopping-modal`) rendered on top of the `running` screen. It is shown when **Stop Run** is pressed (`notifyStopRun`) and hidden when the next WebSocket message reports `panel.screen !== "running"`. While shown, its full-screen backdrop blocks all interaction with the underlying controls.

---

## 3. State Machine Transitions

The flag does not introduce a new screen state. It is a modal overlay whose visibility is driven by the user's **Stop Run** action and the backend `panel.screen` value. The relevant transitions:

```
running [flag hidden] --[user presses "Stop Run" → notifyStopRun()]--> running [flag shown: "Stopping Run…"]
running [flag shown]  --[WebSocket: panel.screen !== "running" → hideRunStoppingModal()]--> ready / complete [flag hidden]
running [flag shown]  --[/button/stop fetch throws → hideRunStoppingModal()]--> running [flag hidden, Stop Run re-enabled]
```

Notes:
- The flag is shown immediately and optimistically on click (`notifyStopRun`), before the backend confirms the stop.
- The flag stays up for the entire interval the backend continues to report `panel.screen === "running"`, i.e. until the machine has finished stopping.
- The only states that dismiss the flag are: any non-`running` screen arriving over the WebSocket (normal stop → `ready`, or a run that completed first → `complete`), or a failed `/button/stop` request (error path re-enables the Stop Run button so the user can retry).

---

## 4. Screen Designs

### Screen: `running`

**Layout:**

- Full-screen dim backdrop (semi-transparent overlay, `z-index: 10`) covering the `running` screen and blocking interaction.
- Centered modal card: white fill, red (`#b91c1c`) border, with bold red text "Stopping Run…".
- No close button (user cannot dismiss it; it clears automatically).
- While stopping process is ongoing, "., .., ..." animation is shown.

**Dynamic content:**

- Centered modal card shows in bold text "Stopping Run"

**User interactions:**

- No User Interactions. User cannot dismiss the flag and it clears automatically when the machine has finished stopping the run.

**Error states:**

- **Handled — stop request fails to send:** if `POST /button/stop` throws (network error / rejection), the flag is hidden, `isStoppingRun` is reset, and the **Stop Run** button is re-enabled so the user can retry. No error message is shown; the UI simply reverts to the running state.

---

## 5. Data Binding

- None

---

## 6. Accessibility / Kiosk Constraints

- Flag has no interactive features. This is intended as it notifies the user that the machine is in the process of stopping the run.

---

## 7. Assets

- None

---

## 8. Acceptance Criteria

- [ ] Identify why the “Stopping Run…” message is not rendering or persisting visibly during shutdown
- [ ] Ensure users receive immediate visual feedback after pressing “Stop Run”
- [ ] Display a clear loading/stopping state until the run has fully terminated
- [ ] Prevent duplicate stop button presses while shutdown is in progress
- [ ] Verify the UI updates correctly during both fast and slow shutdown scenarios

---

## 9. Open Questions

