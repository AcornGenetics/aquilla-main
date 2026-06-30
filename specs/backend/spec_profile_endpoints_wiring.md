# Backend Spec: Structured Profile Endpoint Wiring — issue #201 (A3)

**Status:** Draft
**Author:** Aquila Engineering Team
**Last updated:** 2026-06-25
**GitHub issue:** #201
**Source file(s):** `aquila_web/main.py`, `tests/contract/test_profile_endpoints.py`
**Umbrella PRD:** `specs/prd/structured-profile-editor-prd.md` · **Decision:** ADR-018
**Builds on:** `spec_stages_contract_foundation.md` (#197), `spec_profile_step_assembly.md` (#198), `spec_stages_validation.md` (#199)

---

## 1. Overview

Wire the pure `validate_stages` (A2) and `assemble_steps` (A1) into the live profile endpoints. This is the only A-issue that modifies `main.py`. It turns a structured-profile save into: validate → (reject with 4xx, or) assemble `steps` and persist; and exposes a `structured` flag on the profile list so the UI can route rows.

---

## 2. Endpoints

### `POST /profiles` (extended)

When `payload.stages` is present:
1. Call `validate_stages(stages)` **first**.
2. If it returns any errors → `HTTPException(status_code=400, detail={"errors": [...]})`; **nothing is written**.
3. Otherwise set `base_profile["steps"] = assemble_steps(stages)` (regenerate from stages — any client-sent `steps` is ignored for structured saves) and persist both `stages` and `steps`.

When `payload.stages` is absent: unchanged legacy behavior (client `steps` saved as-is, no validation).

**Order guarantee:** `validate_stages` is always called before `assemble_steps`, so the assembler only ever runs on validated input (it assumes well-formed data — A1).

| Code | Condition | Body |
|------|-----------|------|
| 200 | valid `stages` (or legacy save) | `{"ok": true, "id": "..."}` |
| 400 | `stages` present and invalid | `{"detail": {"errors": ["<field>: Invalid Value", ...]}}` |
| 403 | target inside `profiles/bundled/` | (unchanged) |

### `GET /profiles` (extended)

Each profile entry gains `structured: bool` — `true` iff the profile's JSON contains a `stages` key. Lets the list route: structured → builder, legacy → read-only view. All other fields unchanged.

---

## 5. Persistence

A structured save writes a JSON carrying both `stages` (source of truth) and the regenerated `steps` (what the runner reads). `steps` is never reverse-parsed; on every structured save it is rebuilt from `stages`.

---

## 8. Contract Tests

`tests/contract/test_profile_endpoints.py` (marked `contract`):
- POST valid `stages` → 200; written JSON has `stages` **and** an assembled `steps` (fixed head/tail + amplification repeat present).
- POST out-of-range `stages` (e.g. temp 200) → 400; nothing written.
- POST malformed `stages` (missing sub-stage `name`) → **400, not 500** (validate guards before assemble).
- `GET /profiles` → a structured profile has `structured: true`; a legacy profile has `structured: false`.

Run: `pytest tests/contract/test_profile_endpoints.py -v`

---

## Out of Scope

- The pure assembler/validator themselves — A1 (#198) / A2 (#199), already merged.
- The builder UI, validation display, list routing in the browser — B1/B2/B3.
- `GET /profiles/details` returning `stages` — already shipped in #197.

## 9. Open Questions

- [ ] Error body shape chosen: `detail={"errors": [...]}`. Revisit if the frontend wants a different envelope (B-side validates independently, so no hard dependency).
