# Frontend / UI Spec: Dev-Only Mouse Cursor Restore

**Status:** Active
**Author:** Jack Hu
**Last updated:** 2026-07-01
**GitHub issue:** #285
**Affected screens:** All UI pages + boot splash
**Source file(s):** `aquila_web/static/styles.css`, `aquila_web/static/splash.html`

---

## 1. Overview

The kiosk cursor-removal work suppressed the pointer at two layers:

1. **X-server level** (PR #153, `specs/hardware/mouse-cursor-removal.md`):
   `xserver-command=X -nocursor` in the LightDM config plus an
   `xsetroot -cursor_name none` backup, written by the deploy scripts. The pointer
   sprite is never rendered on the device.
2. **In-page CSS** (PR #126): `* { cursor: none !important; }` in
   `aquila_web/static/styles.css` and inline in `splash.html`, added as
   defence-in-depth before the X-server fix existed.

Layer 2 applied to *any* browser rendering the pages — including the dev environment
(backend run locally with `AQ_DEV_SIMULATE=1`, viewed in a desktop browser) — making
the cursor invisible while developing.

**Resolution: remove layer 2 entirely.** The cursor becomes visible in dev (with the
correct contextual cursors — `pointer` on buttons, `not-allowed` on disabled controls —
already defined in `styles.css`), and the device keeps hiding it via the X server.

---

## 2. Fleet Assumption (load-bearing)

This change is safe **only because every deployed SENTRI has been provisioned with the
wave-2 X-server fix** (confirmed by the maintainer, 2026-07-01). The CSS rule was those
devices' only cursor suppression prior to that, since OTA container updates do not
rewrite host-level LightDM config.

Consequences:

- Cursor hiding on the device is now **exclusively** X-server-level. The deploy scripts
  self-test it (`run_test "cursor disabled (-nocursor)"`), which is the guard for
  future/re-imaged units.
- App CSS and pages must never reintroduce `cursor: none` — that is pinned by
  `unit_tests/test_dev_cursor_static.py`.

## 3. Change

| File | Change |
|------|--------|
| `styles.css` | Removed `* { cursor: none !important; }`; comment documents why it must not return |
| `splash.html` | Removed the identical inline rule |
| All pages pinning `styles.css` | Cache-buster bumped to a uniform `?v=237` so cached copies of the old CSS are not served |

An interim design (a `dev-cursor.js` shim toggling the rule via a `dev-cursor` class on
`<html>`, keyed off `/button_status.dev_simulate`) was implemented and then removed in
favour of this simpler rollback once the fleet assumption was confirmed. No trace of it
remains; a regression test asserts that.

Not changed: deploy scripts, X-server config, `xsetroot` backup, and the unrelated
work bundled in PRs #125/#126 (Plymouth logo rotation, Chromium `--hide-scrollbars`).

---

## 4. Behaviour Matrix

| Environment | Cursor |
|---|---|
| Physical SENTRI (provisioned with PR #153) | hidden — X server never renders the sprite |
| Dev browser (`AQ_DEV_SIMULATE=1` or not) | visible, contextual (`pointer`, `not-allowed`, …) |
| Mis-provisioned / pre-wave-2 device | **visible** — accepted risk; caught by deploy-script `run_test` |

---

## 5. Testing

CI runs no pytest — verify locally: `pytest tests unit_tests -v`.

**Unit seam (`unit_tests/test_dev_cursor_static.py`):**

- [x] No shipped stylesheet sets `cursor: none`
- [x] No HTML page (splash included) sets `cursor: none` inline
- [x] The interim `dev-cursor.js` shim and all references to it are gone

**Contract seam (`tests/contract/test_button_endpoints.py`):**

- [x] `GET /button_status` includes boolean `dev_simulate` reflecting `AQ_DEV_SIMULATE`
      (still used by `script.js` dev behavior; unrelated to cursor after the rollback)

**Manual / hardware:**

- [ ] Dev browser: cursor visible, `pointer` over buttons
- [ ] Physical SENTRI: cursor absent (X-server `-nocursor`)

---

## 6. Acceptance Criteria

- [ ] Cursor is visible on all UI pages in a desktop browser (dev)
- [ ] Physical SENTRI shows no cursor (X-server layer, unchanged)
- [ ] No app CSS/HTML reintroduces `cursor: none` (regression-tested)
- [ ] Full suite passes locally: `pytest tests unit_tests -v`

---

## 7. Related

- Original cursor removal (X-server layer): `specs/hardware/mouse-cursor-removal.md`
- CSS rule origin: PR #126; X-server fix: issue #152 / PR #153
- GitHub issue: #285
