# Backend / API Spec: [Feature or Endpoint Group Name]

**Status:** Draft | Review | Active | Deprecated
**Author:** [Name]
**Last updated:** YYYY-MM-DD
**GitHub issue:** #[number]
**Source file(s):** `aquila_web/[filename].py`

---

## 1. Overview

What API surface does this spec describe? One sentence.

---

## 2. Endpoints

### `[METHOD] /api/[path]`

**Purpose:** [One sentence]

**Auth required:** Yes | No | [describe]

**Request body:**
```json
{
  "field_name": "string",   // description
  "another_field": 0        // description, required/optional
}
```

**Response (200 OK):**
```json
{
  "status": "ok",
  "data": {}
}
```

**Error responses:**

| Code | Condition | Body |
|------|-----------|------|
| 400 | Missing required field | `{"error": "field X required"}` |
| 422 | Validation failure | `{"error": "..."}` |
| 500 | Unexpected server error | `{"error": "internal"}` |

**Side effects:**
- [What this endpoint triggers — e.g., starts a hardware sequence, writes to DB]
- [Any state machine transitions]

---

## 3. WebSocket Events (if applicable)

### Server → Client

| Event | Payload | When sent |
|-------|---------|-----------|
| `state_update` | `{"screen": "...", "step": N}` | On state machine transition |
| `error` | `{"code": "...", "msg": "..."}` | On recoverable error |

### Client → Server

| Event | Payload | Effect |
|-------|---------|--------|
| `command` | `{"action": "start"}` | Triggers run sequence |

---

## 4. Data Models

### `[ModelName]`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Unique identifier |
| `created_at` | ISO 8601 datetime | Yes | Creation timestamp |

---

## 5. Database / Persistence

- Storage: Local SQLite | Cloud DB | JSON file | In-memory
- File/table: [path or table name]
- Schema changes: [describe or "see migration in scripts/"]
- Data retention: [how long, what gets deleted]

---

## 6. Background Jobs / Tasks

If this feature involves background work:

- What runs in the background?
- How is it triggered and terminated?
- What happens if it crashes mid-run?

---

## 7. Validation Rules

| Field | Rule | Error message |
|-------|------|---------------|
| `[field]` | Must be > 0 | "X must be positive" |
| `[field]` | One of: [A, B, C] | "Invalid value for X" |

---

## 8. Contract Tests

Tests that verify this API contract are in:
- `tests/contract/test_[name].py`

Run: `pytest tests/contract/test_[name].py -v`

---

## 9. Open Questions

- [ ] [Question] — Owner: [name]
