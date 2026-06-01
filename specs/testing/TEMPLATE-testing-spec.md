# Testing Spec: [Feature or Module Name]

**Status:** Draft | Review | Active | Deprecated
**Author:** [Name]
**Last updated:** YYYY-MM-DD
**GitHub issue:** #[number]
**Tests location:** `tests/[path]/` and/or `unit_tests/[path]/`

---

## 1. Scope

What is being tested? Which module, endpoint, or behavior?

---

## 2. Test Types Required

| Type | Location | Framework | Purpose |
|------|----------|-----------|---------|
| Unit tests | `tests/unit/` | pytest | Pure logic, no I/O |
| Contract tests | `tests/contract/` | pytest + httpx | API shape verification |
| Integration tests | `tests/integration/` | pytest | Multi-component behavior |
| E2E tests | `tests/e2e/` | pytest | Full run from input to output |
| Hardware tests | `tests/` marked `@pytest.mark.hardware` | pytest | Requires physical device |

---

## 3. Unit Tests

### `test_[module_name].py`

**File:** `tests/unit/test_[name].py`

| Test name | Input | Expected output | Edge case? |
|-----------|-------|-----------------|------------|
| `test_[name]_happy_path` | [describe] | [describe] | No |
| `test_[name]_empty_input` | `[]` | `ValueError` | Yes |
| `test_[name]_all_zeros` | `[0,0,0]` | `None` | Yes |

**Fixtures used:** [list or "none"]

**Mocks/stubs needed:** [list or "none"]

---

## 4. Contract Tests

**File:** `tests/contract/test_[endpoint].py`

For each endpoint being tested:

| Endpoint | Test case | Expected status | Expected body shape |
|----------|-----------|-----------------|---------------------|
| `POST /api/[x]` | Valid payload | 200 | `{"status": "ok"}` |
| `POST /api/[x]` | Missing field | 400 | `{"error": ...}` |

---

## 5. Integration Tests

**File:** `tests/integration/test_[name].py`

Describe what components are wired together and what behavior is being verified end-to-end.

- Components involved: [e.g., FastAPI + state machine + hardware stub]
- Fixtures/setup: [what needs to be initialized]
- Teardown: [any cleanup required]

---

## 6. Simulation Mode

Tests that require hardware must either:
a. Run with `SIMULATION=true` and test the stub behavior, OR
b. Be marked `@pytest.mark.hardware` with a docstring explaining why simulation is insufficient.

**Never skip a test silently.** If hardware is unavailable, the test must either pass in sim mode or be explicitly marked as hardware-only.

---

## 7. Fixtures

| Fixture name | File | Purpose |
|-------------|------|---------|
| `[fixture_name]` | `tests/[subdir]/conftest.py` | [what it provides] |

---

## 8. Coverage Targets

| Module | Target coverage | Current (approx) |
|--------|----------------|------------------|
| `aq_curve/` | 80% | [%] |
| `aquila_web/` | 70% | [%] |
| `aq_lib/` | 60% (sim mode) | [%] |

---

## 9. Running the Tests

```bash
# Full suite
pytest tests unit_tests -v

# Specific module
pytest tests/unit/test_[name].py -v

# Skip hardware tests
pytest tests -v -m "not hardware"

# Coverage report
pytest tests --cov=aq_curve --cov-report=term-missing
```

---

## 10. Known Gaps

- [Tests that don't exist yet and why — technical debt to track]
