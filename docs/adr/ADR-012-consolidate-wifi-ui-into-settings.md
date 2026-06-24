# ADR-012: Consolidate Wi-Fi UI into Settings, retire the duplicate

**Status:** Accepted
**Date:** 2026-06-16
**Author:** Claude (paired with maintainer)
**Deciders:** Maintainer, via issue #167

---

## Context

Issue #167 moves the **Wi-Fi & System** and **Updates** functional pages out of the
Help section into a new top-nav **Settings** item. While implementing it, we found
**two** separate Wi-Fi user interfaces in the codebase:

- `aquila_web/static/help.html` `tab-wifi` — the version actually shown to users
  today (inside Help). Supports status, scan, and connect only.
- `aquila_web/static/wifi.html` — a standalone page served at `/wifi`. It is a strict
  **superset**: status, scan, connect **plus Forget network and a Saved Connections
  list**. Its extra endpoints (`/wifi/forget`, `/wifi/saved`) are already implemented
  and live in `main.py`. Nothing in the nav links to `/wifi`; it is effectively
  orphaned.

"Move the existing Wi-Fi & System content" was therefore ambiguous: the copy literally
inside Help is the weaker one, but a more complete, already-wired implementation exists
unused. Doing nothing would have shipped Settings with the lite UI and left the richer
orphan to rot (or be deleted later as dead code).

Frontend is plain HTML served via `FileResponse` with no templating engine
(see ADR-003), so each page carries its own hand-duplicated nav and its own inline JS.

---

## Decision

**We will make the standalone `wifi.html` UI the canonical Wi-Fi & System interface,
fold it into the new `settings.html` page, retire the lite copy in Help, and redirect
`/wifi` to `/settings`.**

Concretely:

- `settings.html` (new, served at `/settings`) hosts two pill-tabs — **Wi-Fi & System**
  (ported from `wifi.html`, including Forget + Saved Connections) and **Updates**
  (ported from `help.html`'s OTA logic).
- `help.html` loses both functional tabs and their inline JS; it gains two
  **informational** how-to tabs (Wi-Fi Setup, Updates) that point users at Settings.
- `/wifi` becomes a redirect to `/settings`; `wifi.html` is deleted once its markup is
  ported.
- The update-available badge moves from the `?` link to the Settings nav link.

Reversible in principle (the lite version lives in git history), but practically this
sets the single source of truth for the Wi-Fi UI going forward.

---

## Consequences

### Positive
- One Wi-Fi UI to maintain instead of two divergent copies.
- Users gain Forget + Saved Connections, which were built but never reachable.
- `/wifi/forget` and `/wifi/saved` endpoints stop being dead code.
- Old `/wifi` bookmarks/deep links keep working via the redirect.

### Negative
- Larger change than a pure "move the content" reorganization — the Settings Wi-Fi tab
  is the richer page, not a byte-for-byte move of what was in Help.
- The nav link must be hand-edited into all 8 live nav-bearing pages (no shared
  template; consistent with ADR-003).

### Neutral / Tradeoffs
- The sub-tab keeps the label "Wi-Fi & System" although there is still no dedicated
  "System" content — preserved to match issue #167 and the prior Help label.

---

## Alternatives Considered

### Option A: Move the lite Help `tab-wifi` as-is
**Why rejected:** Ships the weaker UI and leaves the superior, already-wired `wifi.html`
as orphaned dead code.

### Option B: Keep both (`/wifi` standalone + a copy in Settings)
**Why rejected:** Two copies of the same Wi-Fi UI to keep in sync — the exact problem
this ADR removes.

---

## Revisit Conditions

- If real "System" controls (reboot/shutdown/diagnostics) are added, reassess whether
  Wi-Fi and System should be separate sub-pages rather than one tab.
- If a frontend templating/build step is adopted (superseding ADR-003), the per-file
  nav duplication this decision lives with should be refactored into a shared header.

---

## References

- Related ADRs: ADR-003 (plain HTML, no build frontend), ADR-011 (wifi bssid & chromium cache)
- Issue: #167
