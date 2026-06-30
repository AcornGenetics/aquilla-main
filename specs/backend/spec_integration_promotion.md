# Spec: Structured Profile Editor — Integration & Promotion (C) — issue #204

**Status:** Draft
**Author:** Aquila Engineering Team
**Last updated:** 2026-06-26
**GitHub issue:** #204
**Type:** Integration / verification + promotion (HITL) — not a red-green feature build
**Umbrella PRD:** `specs/prd/structured-profile-editor-prd.md` · **Decision:** ADR-018

---

## 1. Overview

The convergence step. A1–A4 (backend) and B1–B4 (frontend) were built and tested **in isolation** — the backend against hand-written `stages` payloads, the frontend against the #197 stub. C is the first time they run **together** against the real endpoints on `updated-profiles`: it verifies the assembled whole end-to-end, resolves any contract drift, then promotes the entire feature to `main` in one reviewed PR that closes the whole epic.

No new feature code is expected. C's "tests" are the **already-written** e2e suites (from B1–B4), now pointed at the real backend for the first time; C makes the integrated system pass them and fixes any integration-only gaps it surfaces.

---

## 2. Scope of merged work being integrated

- **Backend:** A1 #198 (`assemble_steps`), A2 #199 (`validate_stages`), A3 #201 (POST/GET wiring + `structured` flag), A4 #213 (canonical key order).
- **Frontend:** B1 #200 (builder shell), B2 #202 (sub-stages), B3 #203 (validation UX + edit round-trip + list routing), B4 #211 (legacy read-only view).

---

## 3. Verification steps

1. **Backend/unit/contract suite:** `venv/Scripts/python -m pytest unit_tests tests/contract -q`. Expect green except the known pre-existing environmental failures (button/ready-screen state-bleed, device-filtering/results fixtures, profile-dir-state tests). These are identical on `main` (verified during A3) — not introduced here.
2. **e2e against the real backend** (the deferred convergence): with a simulate-mode server running (`AQ_DEV_SIMULATE=1 … uvicorn aquila_web.main:app --port 8090`), run
   `venv/Scripts/python -m pytest tests/e2e/test_profile_builder.py tests/e2e/test_legacy_view.py -q`
   (requires `playwright install chromium`). These exercise: structured create → real validate/assemble → save → reopen → repopulate from `stages`; save-time validation display; sub-stage add/remove; list routing (structured → builder, legacy → read-only view).
3. **Resolve integration drift** if any surfaces — most likely the stylesheet cache-buster uniformity check (`test_settings_nav`) now that `builder.html` is a live page, or any field-id/payload mismatch between what the builder POSTs and what the backend expects.

## 4. Promotion

- Open a single PR **`updated-profiles` → `main`**.
- Body must list: `Closes #197, #198, #199, #200, #201, #202, #203, #211, #213` so merging to the default branch auto-closes the whole epic.
- Reviewed + merged as one unit. (#204 itself closed manually or via the PR.)

---

## 5. Acceptance criteria

- [ ] Full `pytest unit_tests tests/contract` run reviewed; only known pre-existing environmental failures remain.
- [ ] e2e `test_profile_builder` + `test_legacy_view` pass against the real backend.
- [ ] Any integration drift fixed (or explicitly deferred with a tracked issue).
- [ ] Promotion PR `updated-profiles` → `main` opened with the full `Closes …` list.

## 6. Out of scope

- New feature behavior — owned by A1–A4 / B1–B4.
- Rewriting already-saved profile files (A4 normalizes on next save only).

## 7. Open Questions

- [ ] If the cache-buster uniformity test fails, fix here (align `?v=` across pages) or split into its own follow-up issue? (Lean: quick fix here if trivial.)
