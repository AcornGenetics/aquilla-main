# Backend Spec: Canonical Profile JSON Key Order — issue #213 (A4)

**Status:** Draft
**Author:** Aquila Engineering Team
**Last updated:** 2026-06-26
**GitHub issue:** #213
**Source file(s):** `aquila_web/main.py`, `tests/contract/test_profile_endpoints.py`
**Umbrella PRD:** `specs/prd/structured-profile-editor-prd.md` · **Decision:** ADR-018
**Supersedes helper:** `_order_time_fields()` (the targeted 2-key reorder this generalizes)

---

## 1. Overview

Structured Profiles save their top-level JSON keys in an inconsistent order vs Legacy Profiles (`steps` floats to the top, `post_in_gui`/`stages`/`labels` land in the wrong spots) because `save_profile` builds the dict by insertion order. This issue enforces one canonical key order on every saved profile. Purely a serialization/ordering change — **no values or semantics change**.

---

## 2. Canonical order

Order the keys that are present into this sequence; any other/unknown top-level keys are preserved and appended after, in their original relative order (never dropped):

1. `output_dir`
2. `post_in_gui`
3. `title`
4. `rox_unavailable` *(when present)*
5. `time_unavailable`
6. `estimated_completion_seconds`
7. `labels`
8. `stages` *(structured profiles only)*
9. `steps`

Rationale: metadata first (matches legacy), then the human-authored `stages`, then the large machine-facing `steps` last. `stages` immediately precedes `steps`.

**Decisions (resolved):**
- **`labels` placement:** with the metadata, after `estimated_completion_seconds`, before `stages`. ✔
- **Scope:** **structured saves only** (a profile whose `base_profile` has a `stages` key). Legacy/`steps`-based saves keep the existing `_order_time_fields` behavior unchanged. ✔

---

## 3. Implementation

- Add `_order_profile_keys(profile: dict) -> dict` in `main.py`: build a new dict by walking the canonical list and copying present keys, then append any leftover keys. Pure dict→dict.
- `save_profile` calls `_order_profile_keys(base_profile)` immediately before writing **when `base_profile` has a `stages` key** (structured); otherwise it keeps the existing `_order_time_fields(base_profile)` call. The countdown keys are already set on `base_profile` before this point, so ordering need not inject them.
- Keep the existing "both countdown fields always present, positioned after the anchor" guarantee intact (canonical order keeps `time_unavailable` → `estimated_completion_seconds` right after `title`/`rox_unavailable`).

---

## 8. Tests

`tests/contract/test_profile_endpoints.py` (marked `contract`; prior art: `test_saved_file_always_carries_both_fields_after_anchor`, which reads the written file from disk):
- A saved **structured** profile's top-level keys equal the canonical order (filtered to present keys); `stages` immediately precedes `steps`; `steps` is last. (`tests/contract/test_profile_endpoints.py::test_structured_profile_keys_in_canonical_order`)
- Unit tests for the pure `_order_profile_keys`: canonical order regardless of input order; only-present keys emitted; `rox_unavailable` placement; **unknown keys preserved, never dropped** (`unit_tests/test_profile_key_order.py`).
- **Legacy/steps-based saves are unchanged** — the existing countdown-field ordering test (`test_saved_file_always_carries_both_fields_after_anchor`) still passes.

Run: `pytest tests/contract/test_profile_endpoints.py -v`

---

## Out of Scope

- Re-ordering already-saved profile files on disk (this only affects writes; existing files normalize on their next save).
- Any change to `stages`/`steps` content — A1/A2/A3 own those.

## 9. Open Questions

- None — `labels` placement and structured-only scope both resolved above.
