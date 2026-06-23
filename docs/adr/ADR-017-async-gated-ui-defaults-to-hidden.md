# ADR-017: Async-gated UI elements default to hidden in markup

**Status:** Accepted
**Date:** 2026-06-23
**Author:** Rasita Vajapattana
**Deciders:** Rasita Vajapattana

> Numbering note: this branch is cut from `main` (latest ADR-015). ADR-016 is
> reserved by the in-flight rebrand branch (#189), so this decision takes 017
> to avoid a collision regardless of merge order.

---

## Context

The web UI (`aquila_web`) serves its pages as **static HTML files** via FastAPI `FileResponse` — there is no server-side templating. Any element whose presence depends on runtime state (dev vs. non-dev mode, feature flags, fetched config) therefore has its visibility decided **client-side**, after an asynchronous fetch resolves.

The Run page has a dev-only "Optics path" field (`#run-optics-tab`). It was authored visible in the static markup, and JS hid it after `fetch("/button_status")` resolved with `dev_simulate=false`. Because the fetch is async, the field painted visible on first frame and was only hidden once the callback ran — a flash-of-unhidden-content (FOUC) that end users saw on every navigation to `/run` in non-dev mode (see issue #193).

The constraints that make this a recurring trap:

- Static markup paints **before** any JS runs; the initial class list is what the user sees first.
- Fetch-gated visibility means there is always a gap between first paint and the state-resolving callback.
- Defaulting to *shown* means the failure mode leaks privileged/dev-only UI to users; defaulting to *hidden* means the worst case is a correct-but-slightly-late reveal.

Doing nothing leaves every current and future async-gated control exposed to the same flash.

## Decision

**We will author every UI element whose visibility depends on async/runtime state as hidden by default in static markup (`is-hidden`), and reveal it from JS only once the state is known.**

Concretely:

- New dev-only, flag-gated, or fetch-gated elements ship with `class="... is-hidden"` in the `.html` file.
- The JS that resolves the state uses a **forced** toggle, e.g. `el.classList.toggle("is-hidden", !shouldShow)`, so it reveals when the condition holds and is a harmless no-op when it does not.
- The reference fix: `#run-optics-tab` in `aquila_web/static/run.html` now ships `is-hidden`; `setOpticsVisibility(isDev)` reveals it only in dev mode.

This is reversible per-element (it's a CSS class on markup) but is adopted as the standing convention for the static-file web UI.

## Consequences

### Positive
- No FOUC: dev-only / gated UI never flashes in front of users.
- Fail-safe default — a missing or failed state fetch leaves gated UI hidden rather than exposed.
- Cheap and uniform: one utility class (`.is-hidden { display: none }`) plus a forced toggle.

### Negative
- Gated elements that *should* show appear a frame late (after the fetch) instead of immediately. Acceptable: a slightly-late correct reveal beats an early wrong one.
- Relies on JS running; if JS fails entirely, gated elements stay hidden (acceptable, and correct for dev-only controls).

### Neutral / Tradeoffs
- Slightly more discipline at authoring time — the default class must be remembered. The regression test on the Run page guards the one known case; new cases rely on this ADR plus review.

## Alternatives Considered

### Option A: Keep visible-by-default, hide via JS
**Why rejected:** This is the exact bug — guarantees a flash and leaks dev-only UI to users on every load.

### Option B: Server-side render visibility (template the HTML per request)
**Why rejected:** The web UI is intentionally static `FileResponse`; introducing templating for one class toggle is disproportionate and changes the serving architecture.

### Option C: Inline `<style>`/blocking script in `<head>` to set visibility pre-paint
**Why rejected:** More complex, still needs the state which is fetched async; the default-hidden class achieves the same fail-safe with one attribute.

## Revisit Conditions

- If the web UI moves to server-side templating or a SPA framework that resolves state before first paint, this convention can be relaxed.
- If a future element genuinely must be visible-by-default and only conditionally *hidden* (inverse case), document the exception and ensure the hidden-state default still cannot leak privileged UI.

## References

- Issue: #193
- Related ADRs: ADR-012 (custom dropdowns as cosmetic overlays — UI-convention precedent)
- Code: `aquila_web/static/run.html`, `aquila_web/static/script.js` (`setOpticsVisibility`)
- Test: `tests/contract/test_optics_path_endpoints.py::test_run_page_hides_optics_tab_by_default`
