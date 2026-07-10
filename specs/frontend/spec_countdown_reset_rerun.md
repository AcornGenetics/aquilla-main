# Frontend / UI Spec: Countdown timer survives Reset + re-run

**Status:** Draft
**Author:** Jack Hu
**Last updated:** 2026-07-10
**GitHub issue:** #312
**Affected screens:** Run (running state)
**Source file(s):** `aquila_web/static/script.js`
**Related:** feature spec `specs/frontend/countdown-timer.md` (#110/#121); interacting change #275 (Reset clears `selected_profile` server-side)

---

## 1. Overview

Bug fix. The countdown timer added in #110/#121 regresses to the stopwatch after a
run completes, the operator hits **Reset**, and then re-runs the **same** profile.
The first run correctly shows the **countdown** ("Time Remaining"); the second run
shows the **stopwatch** ("Elapsed Time") even though the profile still has an estimate.

The fix makes the countdown-vs-stopwatch decision at run start derive from the
**authoritative active profile**, not from a client-side cache that is only warmed
by the selection UI event.

No visible design changes. The countdown / stopwatch presentation, the "Finishing
Run" overlay, and all wording remain exactly as specified in
`specs/frontend/countdown-timer.md`. This spec only changes *when and how the mode is
decided*.

---

## 2. Root cause

The mode decision depends entirely on `cachedEstimateSeconds`, which is written
**only** by `loadProfileLabels()` (`script.js:146`, `:166`). `loadProfileLabels()`
is called only from selection paths:

- the dropdown `change` handler (`script.js:1394`), and
- the initial page-load restore (`script.js:1350`).

`beginTimerMode()` blindly trusts that cache on the transition into `running`
(`script.js:225-231`, called at `script.js:626`). `notifyRun()` re-syncs
`/profile/select` to the server before running (`script.js:798`) but never refreshes
the estimate cache.

**Reset clears the profile server-side** (added for #275): Reset →
`resetRunScreen()` → `POST /run/complete/ack` → `_set_selected_profile(None)`
(`main.py:895`), persisted to disk. When the profile is subsequently restored from
server/persisted state (page reload or ready-screen reconciliation) **without going
back through `loadProfileLabels()`**, `cachedEstimateSeconds` is stale/`null` while
the profile still looks selected. The next run's `beginTimerMode()` reads `null` and
falls back to the stopwatch.

The first run works because the operator's manual selection warmed the cache; the
second run reuses the profile without re-selecting, so the cache is never re-warmed.

---

## 3. Fix

Derive countdown mode at run start from the **authoritative selected profile**, not
the UI-populated cache.

`beginTimerMode()` becomes authoritative: on the transition into `running` it
fetches the estimate for the **active run profile** and sets the mode from that.

- The active profile is `activeRunProfileName` — set from the server-authoritative
  WebSocket panel (`panel.profile_name`, `script.js:617-619`) **before**
  `beginTimerMode()` is called (`script.js:626`). It is a human-readable display
  name (`_resolve_profile_display_name`, `main.py:121`), which `/profiles/details`
  resolves via its `?name=` lookup (`main.py:1831-1844`). That lookup **must be
  recursive** (`rglob`) — profiles live in `bundled/` and `local/` subdirs, so a
  non-recursive `glob` 404s every profile looked up by name and the fix silently
  stays on the stopwatch. See §7.
- This also covers runs started by the device's **physical button**, which bypass
  `notifyRun()` entirely.

### 3.1 Behavior

1. **Fast path (no flash).** On entering `running`, apply the mode from
   `cachedEstimateSeconds` immediately so a warm cache renders the correct label on
   the first tick with no network round-trip.
2. **Authoritative path.** Then fetch `/profiles/details?name=<activeRunProfileName>`
   and re-apply the mode from the returned `estimated_completion_seconds`. This
   corrects a cold/stale cache (the #312 case) and warms `cachedEstimateSeconds` for
   the duration of the run.
3. **Fallback.** If `activeRunProfileName` is empty, or the fetch fails / is not
   `ok`, keep the fast-path decision (silently fall back to whatever the cache said,
   i.e. stopwatch when the cache is null) — matching the existing error-state
   behavior in `specs/frontend/countdown-timer.md` §4.
4. **Race guard.** The fetch is async and may resolve after the run has already
   ended or a *different* run has started. Capture a monotonically increasing run
   token when `beginTimerMode()` is entered; only apply the fetched result if the
   token still matches the current run **and** the screen is still `running`. This
   prevents an in-flight fetch from re-enabling countdown mode after Reset or on a
   subsequent stopwatch-only run.

`resetTimerMode()` (leaving `running`) is unchanged in intent — it still sets
`countdownSeconds = null` and the label back to "Elapsed Time" — but it also
invalidates the run token so any in-flight `beginTimerMode()` fetch is ignored.

---

## 4. Data binding (delta from countdown-timer.md §5)

| UI Element | Data Source (was → now) | Update Trigger |
|------------|--------------------------|----------------|
| `#run-timer-label` | Presence of `cachedEstimateSeconds` **→** estimate for the **active run profile**, fetched at run start from `/profiles/details?name=<activeRunProfileName>` (cache used only as a fast-path prime) | On entering `running` |

All other rows in `countdown-timer.md` §5 are unchanged.

---

## 5. Acceptance criteria

(From issue #312.)

- [ ] Run a profile with an estimate → countdown ("Time Remaining") shows.
- [ ] After the run completes, hit **Reset**, run the **same** profile again →
      countdown **still** shows (not the stopwatch). *(the regression)*
- [ ] A profile with **no** estimate shows the stopwatch ("Elapsed Time") on both
      the first and every subsequent run.
- [ ] An in-flight estimate fetch that resolves after Reset (or after a later
      stopwatch-only run starts) does **not** flip the timer back to countdown.
- [ ] Regression coverage exists for the reset → re-run path (not just DOM presence).

---

## 6. Test plan

### 6.1 E2E live-run regression — `tests/e2e/test_countdown_timer.py` (`e2e`)

New Playwright test(s) driving an actual simulated run (backend started with
`AQ_DEV_SIMULATE=1`, short `AQ_DEV_RUN_DURATION`). The existing tests in this file
only assert DOM presence (`countdown-timer.md` §9.3); these exercise the live
reset → re-run flow that #312 regressed.

- **`test_countdown_survives_reset_and_rerun`** — select a profile **with** an
  estimate; start a run; assert `#run-timer-label` reads **"Time Remaining"**; let
  it complete; press **Reset**; run the **same** profile again **without** re-opening
  the dropdown; assert the label **still** reads **"Time Remaining"**. Fails on
  today's code (shows "Elapsed Time"); passes after the fix.
- **`test_stopwatch_stays_stopwatch_across_rerun`** — a profile with **no** estimate
  shows **"Elapsed Time"** on the first and second runs (guards against the fix
  wrongly forcing countdown mode).

If the live simulate harness is not reachable in CI, the tests `pytest.skip` using
the same reachability guard as the existing `_goto()` helper, and the flow is added
to the manual dev checklist in `countdown-timer.md` §9.4.

### 6.2 Manual dev checklist addition (`countdown-timer.md` §9.4)

- [ ] Profile **with** estimate → run → Reset → **re-run same profile** → label
      **still** reads "Time Remaining" and counts down.

---

## 7. Server-side dependency

The authoritative run-start fetch calls `/profiles/details?name=<activeRunProfileName>`.
That endpoint's `?name=` branch (`main.py`) must search **recursively** — profiles
live in `bundled/` and `local/` subdirectories, not at the profiles root. It
originally used a non-recursive `glob("*.json")`, so any profile looked up by name
(e.g. **Beer Spoilers - Bacteria** in `bundled/`) returned **404**; the client fetch
then fell through to its `.catch()` and left the timer on the stopwatch — masking the
fix entirely. Changed to `rglob("*.json")`, consistent with
`_resolve_profile_display_name` (`main.py:121`), which produces the very name searched.

Covered by the contract regression `test_profile_details_by_name_resolves_profile_in_subdir`
(`tests/contract/test_profile_endpoints.py`). Note the e2e tests stub
`/profiles/details`, so they cannot catch this — the contract test is the guard.

## 8. Out of scope

- No change to the profile editor, the JSON data model, the "Finishing Run" overlay,
  or the stopwatch/countdown rendering math — all remain as in
  `specs/frontend/countdown-timer.md`.
- #275's server-side clearing of `selected_profile` on Reset is intentional and stays.
