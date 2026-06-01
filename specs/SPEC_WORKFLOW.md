# Spec-Driven Engineering Workflow

## The Core Rule

**No code without a spec.** A spec doesn't have to be long. It has to answer:
what does this do, how do we know it works, and what can break.

---

## Folder Map

```
specs/
  feature/        # User-facing features (UI flows, new assay types, etc.)
  hardware/       # Physical device specs (thermal, motors, sensors, comms)
  backend/        # API endpoints, data models, background jobs
  frontend/       # Screen layouts, state machine transitions, kiosk UX
  analysis/       # Math, curve-fitting, detection logic
  testing/        # Test plans, fixture definitions, coverage targets

docs/
  adr/            # Architecture Decision Records (irreversible or costly choices)
  debugging/      # Known failure modes, diagnostic procedures
  onboarding/     # Getting started, environment setup, team norms
  architecture/   # System diagrams, domain model, data flow
  codebase/       # Module-by-module explanations for new hires

.github/
  ISSUE_TEMPLATE/ # Bug report, feature request, hardware issue templates
  PULL_REQUEST_TEMPLATE.md
```

---

## Before You Write Code

1. **Find or create the relevant spec** in `specs/`.
2. If the spec doesn't exist, write it first — even a stub is fine.
3. Link the spec in the GitHub issue: `Spec: specs/feature/my-feature.md`.
4. If the change touches hardware behavior, also update or create a `specs/hardware/` entry.
5. If the change makes a hard-to-reverse architectural choice, write an ADR in `docs/adr/`.

---

## During Implementation

- Keep the spec open beside your code.
- If you discover the spec is wrong, **update the spec first**, then update the code.
- Don't silently deviate — wrong specs are worse than no specs.
- For analysis changes: verify the math section matches your implementation before committing.

---

## Before PR Review

Checklist (also in PR template):
- [ ] Spec file linked in PR description
- [ ] Spec is accurate and up to date with what was built
- [ ] New tests written per the testing spec
- [ ] Full test suite passes: `pytest tests unit_tests -v`
- [ ] No secrets or `.env` files in diff
- [ ] ADR written if an irreversible architectural decision was made

---

## After Merging

- If a spec was a draft, mark it `Status: Active` at the top.
- Update the `docs/debugging/known-issues.md` if you uncovered new edge cases.
- Add a line to the relevant ADR if an existing decision was revisited.
- If you changed an API endpoint, update `specs/backend/` accordingly.

---

## AI-Assisted Development Rules

### How Claude Should Use Specs

When starting any task, Claude should:
1. Read the relevant spec file verbatim before generating code.
2. Cite the spec section being implemented (e.g., "Per `specs/backend/run-api.md` §3.2...").
3. Refuse to implement anything not described in the spec without flagging it explicitly.

### Avoiding Hallucinations

- Claude must reference **exact file paths and line numbers**, not paraphrases.
- If a spec section is ambiguous, Claude should ask rather than assume.
- Claude should never invent API fields, hardware register addresses, or analysis parameters.
- For hardware behavior, Claude must cite `aq_lib/` source files directly.

### Updating Specs After Code Changes

After any substantive code change:
1. Diff the spec against the new implementation mentally.
2. If the spec is stale, edit the spec file and note `Last updated: YYYY-MM-DD`.
3. Never leave a spec that contradicts the code — delete the spec section rather than leave it wrong.

---
