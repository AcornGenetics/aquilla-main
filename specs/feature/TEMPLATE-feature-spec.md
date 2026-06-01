# Feature Spec: [Feature Name]

**Status:** Draft | Review | Active | Deprecated
**Author:** [Name]
**Last updated:** YYYY-MM-DD
**GitHub issue:** #[number]
**Related specs:** [links to other specs if any]

---

## 1. Problem Statement

What user or operator need does this address? Why now?

Keep this to 2–3 sentences. If you can't explain the problem briefly, the feature isn't scoped tightly enough.

---

## 2. Scope

### In scope
- [Bullet list of what this feature covers]

### Out of scope
- [Explicit exclusions — things that might seem related but are NOT in this spec]

---

## 3. User Flow

Describe the end-to-end experience from the user's perspective.

```
Operator loads assay → selects [X] → device does [Y] → screen shows [Z]
```

Include:
- What the user sees at each step
- What feedback the device/UI gives
- What happens on error

---

## 4. Functional Requirements

List numbered requirements. Each one must be testable.

1. The system SHALL [do X] when [condition Y].
2. The system SHALL display [message Z] if [error condition].
3. The system SHALL NOT [do A] unless [precondition B] is met.

---

## 5. Non-Functional Requirements

- **Performance:** [e.g., response within 200ms, or N/A]
- **Reliability:** [e.g., must survive power interruption at any step]
- **Security:** [e.g., no user data written to disk]
- **Hardware constraints:** [e.g., only runs when lid is closed]

---

## 6. UI/Screen Changes

If this feature changes the kiosk UI, describe:
- Which screens are affected (reference `docs/ui/`)
- New state transitions added to the state machine
- Any new icons, labels, or error messages

---

## 7. API Changes

If this feature adds or modifies API endpoints:
- See `specs/backend/TEMPLATE-backend-spec.md` for format
- List endpoint names here with links

---

## 8. Data / State Changes

- New fields in config or state files?
- New DB columns or documents?
- Changes to `config.json` schema?

---

## 9. Hardware Interactions

Does this feature interact with physical hardware?

- Which subsystems: thermal | motor | LED | ADC | lid sensor | other
- Reference `aq_lib/` module and relevant functions
- Any timing constraints or hardware preconditions

---

## 10. Acceptance Criteria

These must all pass before the feature is considered done:

- [ ] [Specific observable outcome]
- [ ] [Specific observable outcome]
- [ ] Full test suite passes: `pytest tests unit_tests -v`
- [ ] Demo'd on physical device (or simulation mode with documented limitation)

---

## 11. Open Questions

Questions that need answers before or during implementation:

- [ ] [Question] — Owner: [name] — Due: [date]

---

## 12. Implementation Notes

Optional: hints for the implementer, known gotchas, links to prior art in codebase.
