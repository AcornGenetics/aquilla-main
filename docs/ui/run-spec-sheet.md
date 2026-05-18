# Run Page Spec Sheet (`/run`)

## Overview
- Route: `/run` serves `aquila_web/static/run.html`.
- Layout: fixed desktop viewport (800 × 400) with centered main content.
- Page states: `Ready` (default), `Running`, `Results` (hidden via `.is-hidden`).

## Layout & Structure
- App shell: single-column layout inside `.main`.
- Content order in main:
  1. Top buttons row (`History`, `Profiles`)
  2. Page title `Run` (centered)
  3. Ready card with profile select + ready notification
  4. Drawer control buttons (open/close)
  5. Results label text
  6. Running card (elapsed timer, hidden by default)
  7. Results card (table, hidden by default)

## Navigation
- Top buttons:
  - `History` → `/history.html`
  - `Profiles` → `/profiles`

## Components
### Ready Card
- Profile select (`select#mySelect`) with label `Select a profile`.
- Ready notification: `Ready` (`#ready-status`).
- Drawer actions: `Open Drawer`, `Close Drawer` (`.btn.btn-secondary`).
- Results label text: `Results`.

### Running Card
- Heading: `Running`.
- Timer label: `Elapsed Time · 00:00 min` (`#timer` updates).

### Results Card
- Heading: `Results`.
- Table: `#results-table` (full width).

## Typography
- Base font: `Neue Haas Grotesk Display Pro`, fallback system sans.
- Headings: `ABC Favorit Mono` for `h1`.
- Title `Run`: 32px.
- Card headings: 18px, dark green.
- Body text: 14–16px, gray.
- Top button labels: 14px, uppercase, 0.08em letter spacing.

## Color Palette
- Page background: `#f6f6f6`.
- Top buttons: `#c2f282` background, `#184419` text (`.btn-secondary`).
- Card background: `#ffffff`.
- Primary text: `#1a1c1c`.
- Secondary text: `#505050`.
- Primary button: `#184419` background, `#c2f282` text.
- Secondary button: `#c2f282` background, `#184419` text.
- Border gray (inputs): `#e6e6e6`.

## Spacing & Sizing
- Main padding: 48px top/bottom, 56px left/right.
- Card padding: 20px, radius 16px, shadow `0 10px 30px rgba(0,0,0,0.08)`.
- Button row gap: 12px.
- Button padding: 12px 20px, radius 999px.

## States & Behavior
- Hidden sections use `.is-hidden` (`display: none`).
- Buttons hover: `filter: brightness(0.82)`.
- Disabled buttons: 50% opacity, no hover filter.
