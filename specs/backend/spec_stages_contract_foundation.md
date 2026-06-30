# Backend / API Spec: `stages` Contract Foundation (issue #197)

**Status:** Active
**Author:** Aquila Engineering Team
**Last updated:** 2026-06-25
**GitHub issue:** #197
**Source file(s):** `aquila_web/main.py`, `aquila_web/static/profiles/builder.html`, `tests/fixtures/sample_stages.json`
**Umbrella PRD:** `specs/prd/structured-profile-editor-prd.md` · **Decision:** `docs/adr/ADR-018-structured-profile-editor-backend-assembled-steps.md`

---

## 1. Overview

The shared prerequisite for the Structured Profile Editor: make the backend accept, persist, and return a structured `stages` object, and serve the editor's HTML shell. This establishes the `stages` contract both routes build against. It deliberately does **not** assemble `steps`, validate ranges, add the list `structured` flag, or build any UI — those are separate issues (A1 #198, A2 #199, A3 #201, B1–B3) with their own specs.

---

## 2. Endpoints

### `POST /profiles` (extended)

**Purpose:** Accept an optional structured `stages` object and persist it verbatim alongside the existing fields.

**Request body (relevant addition):**
```json
{
  "name": "My Assay",     // required (unchanged)
  "stages": { ... }       // optional; persisted verbatim (see §4)
}
```

**Response (200 OK):** `{ "ok": true, "id": "local/my_assay.json" }` (unchanged).

**Behavior for #197:**
- When `stages` is present, it is written into the saved JSON unchanged.
- When `stages` is absent, behavior is exactly as before (Legacy/`steps`-based saves unaffected).
- No validation of `stages` contents in #197 (deferred to A2/A3). No `steps` regeneration (deferred to A1/A3).

**Error responses:** unchanged from current `POST /profiles` (e.g. 403 on bundled, 500 on write failure).

### `GET /profiles/details` (extended)

Returns the `stages` object **only when the file contains it**; Legacy Profiles omit the key entirely so the presence of `stages` is the Structured-Profile marker. All other returned fields unchanged.

### `GET /profiles/builder` (new)

Serves `static/profiles/builder.html` with `Cache-Control: no-store`. A static shell only — Stage UI, validation, and save wiring are the frontend issues (B1/B2/B3).

---

## 4. Data Models

### `ProfileSave.stages` (request field) — the contract

Optional `dict`. Canonical fixture committed at `tests/fixtures/sample_stages.json`:

```json
{
  "incubation":   { "enabled": true,  "temp": 37, "time": 600 },
  "denaturation": { "enabled": true,  "temp": 95, "time": 120 },
  "amplification": {
    "cycles": 40,
    "subStages": [
      { "name": "Denaturation",          "temp": 95,   "time": 11 },
      { "name": "Annealing & Extension", "temp": 60.5, "time": 38 }
    ]
  },
  "finalHold":    { "enabled": false, "temp": 25, "time": 60 }
}
```

- `incubation` / `denaturation` / `finalHold`: `{enabled: bool, temp: °C, time: seconds}` — optional Stages.
- `amplification`: always present (no `enabled`); `cycles` integer; `subStages` length 2–3, each `{name, temp, time}`.

#197 treats this object as opaque — it stores and returns it without interpreting it.

---

## 5. Persistence

- The `stages` object is written verbatim into the Profile JSON (under `profiles/local/` for new profiles).
- A file containing `stages` is a Structured Profile; its presence is the only marker (ADR-018).
- `steps` remains the only artifact the hardware runner/analytics read. In #197 a structured-only save does not yet regenerate `steps` (that is A1/A3); the field is carried for the contract.

---

## 7. Validation Rules

None in #197. Range/shape validation of `stages` is specified separately for A2 (#199) and enforced on `POST` in A3 (#201).

---

## 8. Contract Tests

`tests/contract/test_profile_endpoints.py` (marked `contract`):
- `test_post_profile_persists_and_returns_stages` — a `stages` payload round-trips through `POST` → `GET /profiles/details`.
- `test_profiles_builder_route_serves_html` — `GET /profiles/builder` returns 200 + HTML.
- `test_sample_stages_fixture_matches_contract` — the committed fixture matches the canonical shape.

Run: `pytest tests/contract/test_profile_endpoints.py -v`

---

## Out of Scope (other issues, other specs)

- Assembling `stages → steps` and the Boilerplate constants — A1 (#198).
- Validating `stages` ranges/shape — A2 (#199).
- Enforcing validation on `POST` and adding the `structured` flag to `GET /profiles` — A3 (#201).
- The builder UI, validation display, and list routing — B1/B2/B3 (#200/#202/#203).

---

## 9. Open Questions

- [ ] None — contract decisions resolved in ADR-018 and the PRD.
