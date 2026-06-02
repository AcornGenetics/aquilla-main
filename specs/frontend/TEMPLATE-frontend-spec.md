# Frontend / UI Spec: [Screen or Flow Name]

**Status:** Draft | Review | Active | Deprecated
**Author:** [Name]
**Last updated:** YYYY-MM-DD
**GitHub issue:** #[number]
**Affected screens:** [list screen names from state machine]
**Source file(s):** `aquila_web/static/[filename]`

---

## 1. Overview

What user-facing flow does this spec describe?

Context: The Aquila UI is plain HTML/JS (no build step, per ADR-003). It runs in Chromium kiosk mode on the Pi display (ADR-005). Screen transitions are driven by a JSON state machine (ADR-006).

---

## 2. Screen Inventory

| Screen ID | Name | Entry condition | Exit conditions |
|-----------|------|----------------|-----------------|
| `home` | Home / Idle | App start or run complete | User taps "Start" |
| `[screen_id]` | [Name] | [When reached] | [What causes transition] |

---

## 3. State Machine Transitions

```
[screen_a] --[user action or event]--> [screen_b]
[screen_b] --[error]--> [error_screen]
[screen_b] --[success]--> [screen_c]
```

Reference the state definitions in: `aquila_web/static/[state-config-file]`

---

## 4. Screen Designs

### Screen: `[screen_id]`

**Layout:**
- Header: [text or dynamic content]
- Body: [describe elements — buttons, progress indicators, data display]
- Footer: [navigation, back button, etc.]

**Dynamic content:**
- [What data is shown and where it comes from — WebSocket event, local state, etc.]

**User interactions:**
- Tap [element] → [action]
- Long-press [element] → [action] (if any)

**Error states:**
- If [condition] → show [message / visual indicator]

---

## 5. Data Binding

| UI Element | Data Source | Update Trigger |
|------------|-------------|----------------|
| [e.g., Temperature display] | WebSocket `state_update.temp` | On each update |
| [e.g., Progress bar] | `state_update.step / total_steps` | On each update |

---

## 6. Accessibility / Kiosk Constraints

- Touch target minimum size: 44×44px
- No hover states (touch-only)
- No text input from virtual keyboard unless explicitly required
- Screen must remain readable at [distance from device]

---

## 7. Assets

| Asset | Path | Format | Notes |
|-------|------|--------|-------|
| Logo | `static/img/logo.svg` | SVG | [any constraints] |

---

## 8. Acceptance Criteria

- [ ] Screen renders correctly at [Pi display resolution]
- [ ] All state transitions work as described
- [ ] Error messages are displayed for all error conditions
- [ ] Tested on physical device (or noted as simulation-only)

---

## 9. Open Questions

- [ ] [Question] — Owner: [name]
