# ADR-019: Destructive Confirmations Use One Shared Custom Modal, Not Native `confirm()`

**Status:** Proposed
**Date:** 2026-06-30
**Author:** Rasita Vajapattana
**Deciders:** Aquila Engineering Team

---

## Context

Two destructive actions in the UI gate themselves behind a browser-native
`window.confirm()`:

- **History delete** — `aquila_web/static/history.js` ("Are you sure you want to
  delete `<run-name>`?", or "… N runs" for a multi-select).
- **Profiles delete** — `aquila_web/static/profiles/profiles.js` ("… N profile(s)?"
  plus a second line listing the selected names).

On the kiosk fleet (ADR-005: Chromium kiosk on Raspberry Pi) a native `confirm()`
renders with OS chrome — system font, no border radius, OS-decided button order — which
is visually inconsistent across machines and clashes with the themed UI, the same class
of problem ADR-012 fixed for the Run-page dropdowns. Kiosk units must look identical, so
app-controlled styling is required.

A `confirm()` is **not** a form control, so ADR-012's pattern (overlay a themed widget on
a hidden native control kept as the source of truth) does not transfer — there is no
element to retain. `confirm()` is a blocking call that returns a boolean. The app already
has a themed dialog idiom for this shape: the `.run-modal` family on the Run page
(dimmed backdrop + white rounded card, `role="alertdialog"`, `is-hidden` toggle) used for
the run-complete / stopping / finishing popups.

The two confirmations are the **same dialog** with different copy — unlike the Run-page
dropdowns, which were two genuinely different widgets (a listbox vs. a typeahead) and so
were deliberately built as bespoke functions rather than a shared component (ADR-012, the
run-dropdowns spec).

Constraints:

- ADR-003: plain HTML/CSS/JS, no build step, no framework, no module bundler. Every page
  loads its own `<script>`; there is currently **no shared frontend JS module** imported
  by more than one page.
- A replacement for `confirm()` must be **async** (a custom modal cannot block), and both
  delete handlers are already `async`, so a `Promise<boolean>` substitutes at the single
  call site without restructuring the handler.

Live options were: (a) two bespoke per-page modals matching ADR-012's "bespoke over
generic" instinct, or (b) one shared `confirmModal()` helper — the app's first shared
frontend JS module — used by both pages.

Doing nothing leaves the kiosk UI visually inconsistent at exactly the moments an operator
is about to destroy data.

---

## Decision

**We will replace the native `confirm()` on both destructive actions with a single shared,
themed `confirmModal()` helper — the app's first shared frontend JS module — that returns
a `Promise<boolean>` and is fail-safe by default.**

Concretely:

- A new shared file (e.g. `aquila_web/static/confirm-modal.js`) exposes one function,
  `confirmModal({ title, message, detail, confirmLabel })`, returning `Promise<boolean>`.
  Both `history.html` and `profiles.html` load it before their page script.
- The helper **injects its own DOM** into `<body>` on first use (one reused instance, one
  modal open at a time) and styles it to match the existing `.run-modal` family, so neither
  page hand-places modal markup.
- It is **fail-safe / default-deny**: it resolves `true` **only** on an explicit Delete-button
  click. Cancel, backdrop tap, `Esc`, and any thrown error while building or showing the
  modal all resolve `false`. The destructive path can only ever fail *closed*.
- Default focus opens on **Cancel** (destructive-safe), and the confirm button is styled as
  a danger action (reusing the existing stopping-red `#b91c1c`, since there is no
  `--danger` token yet).
- Each delete handler changes by **exactly one line** — the boolean-producing step
  (`const confirmed = window.confirm(msg)` → `const confirmed = await confirmModal({…})`).
  Everything downstream (selection gathering, `POST /history/delete` and `/profiles/delete`,
  the reload) is untouched; the backend endpoints do not change.

The helper's API is intentionally limited to the four fields the two callers need — no size
variants, type enums, or icon slots are added speculatively.

This is **reversible with effort** — a page can fall back to native `confirm()` by reverting
its one call site — but the shared helper is the canonical confirmation surface while it exists.

---

## Consequences

### Positive

- Confirmation dialogs are app-controlled and identical across the fleet, matching the
  themed UI (the same goal ADR-012 met for dropdowns).
- One implementation for both deletes — no copy-paste dialog logic to drift between
  History and Profiles; future destructive confirmations reuse it.
- The destructive behavior itself is untouched (one-line swap, backend unchanged), so the
  cosmetic change carries near-zero regression risk to deletion, and the fail-safe default
  means a misbehaving modal cannot delete without explicit confirmation.

### Negative

- Introduces the app's **first shared frontend JS module** — a small departure from the
  "every page owns its JS" status quo. Future readers must know `confirm-modal.js` is a
  shared dependency, and a change to it affects every caller (today: two).
- A second representation of dialog styling now exists alongside `.run-modal`; if the two
  drift, the app shows two dialog looks. (Mitigated by styling the helper from the same
  tokens.)

### Neutral / Tradeoffs

- The helper re-implements dismissal/focus behavior the browser gives for free on a native
  `confirm()`. On a touch kiosk this is acceptable; backdrop-tap-to-cancel is the primary
  dismissal and keyboard (`Esc`) is a low-cost bonus.
- This consciously **reverses ADR-012's "bespoke over generic" instinct** — justified
  because these two callers are the *same* dialog, not two different widgets.

---

## Alternatives Considered

### Option A: Two bespoke per-page modals (one each in History and Profiles)
**Why rejected:** The two confirmations are identical dialog logic with different copy;
two copies would drift, and reuse exists precisely to prevent that. The ADR-012 precedent
for bespoke applied to *different* widgets, which is not the case here.

### Option B: Restyle / re-skin the native `confirm()`
**Why rejected:** Not possible — the OS owns `confirm()`'s rendering; CSS cannot theme it.

### Option C: Adopt a dialog framework / `<dialog>` polyfill component library
**Why rejected:** Violates ADR-003 (no build, no framework) and is far more surface area
than a ~40-line helper needs.

---

## Revisit Conditions

- If the project adopts a frontend framework (reversing ADR-003), prefer a real dialog
  component over a hand-rolled shared helper.
- If a third dialog *shape* appears (not a yes/no confirmation), reconsider whether the
  four-field API should generalize rather than grow flags.
- If the `.run-modal` styling and the confirm-modal styling become a recurring source of
  visual drift, consolidate them into one shared dialog stylesheet.

---

## References

- Related ADRs: ADR-003 (plain HTML/no build), ADR-005 (kiosk host), ADR-012 (custom
  dropdowns as cosmetic overlays — the bespoke-over-generic precedent this reverses)
- Existing dialog idiom: `.run-modal` family in `aquila_web/static/styles.css` /
  `run.html`
- Source files affected: `aquila_web/static/confirm-modal.js` (new),
  `aquila_web/static/history.js`, `aquila_web/static/profiles/profiles.js`,
  `aquila_web/static/history.html`, `aquila_web/static/profiles.html`,
  `aquila_web/static/styles.css`
- Spec: `specs/frontend/` (light frontend spec, to follow)
