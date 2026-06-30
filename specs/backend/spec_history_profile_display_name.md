# Backend Spec: History stores the profile display name, not its file-path id — issue #267

**Status:** Draft
**Author:** Aquila Engineering Team
**Last updated:** 2026-06-30
**GitHub issue:** #267
**Source file(s):** `aquila_web/main.py`, `unit_tests/test_history_profile_name.py`, `tests/contract/test_history_endpoints.py`

---

## 1. Overview

On the **History** page, the **Profile** column shows the profile's file-path id (e.g. `local\A3_Invalid_Temp.json`) instead of the profile's human-readable name (`A3 Invalid Temp`). The user should only ever see the name — never the `local/` directory prefix, the `.json` extension, or the underscores the filename uses in place of spaces.

`POST /profile/select` stores the profile **id** — the relative path emitted by `GET /profiles` (`str(path.relative_to(profile_dir))`, e.g. `local/A3_Invalid_Temp.json`) — in the module-level `selected_profile`. When a run finishes, `_simulate_run` writes that id verbatim into the history entry's `profile` field (`aquila_web/main.py:585`), and `static/history.js` renders `entry.profile` directly. The profile's real display name lives in the profile JSON's `name` field (the same value `GET /profiles` exposes as `name`).

This change resolves the id to the display name when the history entry is built. Purely a stored-value correction — no new endpoints, no schema change.

---

## 2. Behaviour

A new helper `_resolve_profile_display_name(profile_ref: str | None) -> str`:

1. If `profile_ref` is falsy → return `"--"`.
2. **Treat it as a relative-path id:** if `resolve_profile_dir() / profile_ref` is a file, read its JSON and return `name` (falling back to `title`) when present. This is the normal path — the id stored by `/profile/select`.
3. **Otherwise match by name/stem/filename/id** across `resolve_profile_dir().rglob("*.json")` (handles a bare name being passed) and return the matched profile's `name`/`title`.
4. **Fallback:** return `Path(profile_ref).stem` — strips the directory and `.json` so the user never sees a path even if the profile file is missing.

The helper is **idempotent** for a value that is already a display name: passing `"A3 Invalid Temp"` returns `"A3 Invalid Temp"` (matched in step 3, or returned unchanged by the step-4 fallback).

---

## 3. Implementation

- Add `_resolve_profile_display_name` to `main.py` (near `_load_profile_labels`, which already does name/stem/filename matching).
- In `_simulate_run`, set the history entry's `"profile"` to `_resolve_profile_display_name(profile_name)` instead of the raw `profile_name` (`aquila_web/main.py:585`). The results-filename slug, `_load_profile_labels`, and `_profile_rox_unavailable` continue to use the raw id — unchanged.
- In `append_history` (`POST /history/append`), resolve the incoming `profile` the same way before storing — defensive and idempotent.
- The `run_complete` event payload's `profile` is left as-is (out of scope).

---

## 4. Tests

**Unit** — `unit_tests/test_history_profile_name.py` (pure logic, marked `unit`; monkeypatch `resolve_profile_dir` to a tmp dir):
- A profile file at `local/A3_Invalid_Temp.json` with `{"name": "A3 Invalid Temp", ...}` → id `local/A3_Invalid_Temp.json` resolves to `"A3 Invalid Temp"`.
- Result contains no path separator, no `.json`, and no underscore-for-space artifact.
- Passing the already-resolved name `"A3 Invalid Temp"` returns it unchanged (idempotent).
- `None`/empty → `"--"`.
- Missing file (`local/ghost.json`) → falls back to stem `"ghost"` (no path, no extension).

**Contract** — `tests/contract/test_history_endpoints.py`:
- `POST /history/append` with `profile` set to a saved profile's id stores the profile's `name`, not the id (no `\\`, `/`, or `.json` in the stored `profile`).

Run: `pytest unit_tests/test_history_profile_name.py tests/contract/test_history_endpoints.py -v`

---

## Out of Scope

- History entries already written with the old path value — only new runs are corrected (existing files are not rewritten).
- The `run_complete` event payload's `profile` field.
- Any change to `GET /profiles`, profile ids, or on-disk filenames.
