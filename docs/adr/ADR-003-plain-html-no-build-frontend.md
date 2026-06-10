# ADR-003: Plain HTML/CSS/JS Frontend (No Build Step)

**Status**: Accepted  
**Date**: 2026-04-30  
**Deciders**: Aquila Engineering Team

## Context

The Aquila UI runs inside Chromium in kiosk mode on a Raspberry Pi. The UI needs to be simple, touch-optimized, and maintainable without a Node.js/npm ecosystem. Build complexity would slow iteration and add deployment surface area on a resource-constrained device.

## Decision

The frontend is implemented as static HTML files (`run.html`, `history.html`), a single `styles.css`, and plain JavaScript files (`script.js`, `keyboard.js`). No JavaScript framework, bundler, or transpiler is used. Files are served directly by FastAPI's `StaticFiles` mount.

Touch interaction is handled via CSS `touch-action` directives and WebKit-specific momentum-scrolling properties. An on-screen keyboard (`keyboard.js`) is implemented as a custom HTML/JS component for kiosk input.

## Consequences

**Positive**
- Zero build step: changes are live-reloadable; deployment requires only copying files.
- No npm dependency surface; no `node_modules`, no `package.json` CVEs.
- Runs on low-memory Pi hardware without a build toolchain.
- Debugging is straightforward: open DevTools, inspect real DOM/JS.

**Negative**
- No TypeScript: type errors are caught only at runtime or in tests.
- Component reuse is manual (copy-paste or `<script>` include); no module system.
- As complexity grows, lack of framework increases risk of state management bugs.
- No CSS pre-processor: variables and reuse rely on CSS custom properties only.

## Alternatives Considered

- **React/Vue SPA**: richer component model but requires build pipeline, heavier runtime, and adds developer friction.
- **HTMX**: smaller than a full SPA framework but adds a dependency and learning curve.
- **Jinja2 server-side rendering**: simpler than a JS framework but requires a round-trip for every interaction; incompatible with WebSocket-driven live state.
