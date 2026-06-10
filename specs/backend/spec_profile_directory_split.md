# Spec: Profile Directory Split (bundled/ vs local/)

## Problem

All profiles — both image-managed and user-created — live flat in `/opt/aquila/profiles/`. There is no way to distinguish them at runtime, so:

1. Device filtering (`"bundled" in path.parts`) never fires in production — all bundled profiles appear on all devices regardless of `device_profiles.json`.
2. Bundled profiles cannot be force-updated via `cp -f` without risking overwriting user edits.
3. Users can edit or delete bundled profiles through the UI, which causes them to diverge from the image version silently.

---

## Solution

Split `/opt/aquila/profiles/` into two subdirectories:

| Directory | Contents | Managed by |
|---|---|---|
| `/opt/aquila/profiles/bundled/` | Image-managed profiles | Entrypoint (`cp -f` on every start) |
| `/opt/aquila/profiles/local/` | User-created profiles | Never touched by entrypoint |

**Rules:**
- Bundled profiles are **read-only** — cannot be edited or deleted through the UI or API
- To use a modified version of a bundled profile, copy it to `local/` via terminal: `cp profiles/bundled/X.json profiles/local/X_custom.json`
- All profiles from both directories appear in one combined list in the UI
- Device filtering applies only to `bundled/`
- If the same filename exists in both `bundled/` and `local/`, only `local/` is shown (deduplication — local takes priority)

---

## Migration (one-time, permanent no-op after first run)

Devices currently have all files flat in `/opt/aquila/profiles/`. A `_migrate_profiles()` function in `main.py` runs at every startup but only does real work when the flat layout is detected.

### Logic

```
_migrate_profiles():
    if profiles/bundled/ exists AND profiles/local/ exists:
        return  # already migrated, no-op

    load all known bundled filenames from profile_groups.json
        (union of all group lists across all groups)

    for each .json in profiles/ (direct children only, not subdirs):
        if filename is in known bundled filenames:
            if profiles/bundled/<filename> already exists:
                delete the flat file (entrypoint already wrote the image version)
            else:
                move → profiles/bundled/
        else:
            move → profiles/local/

    log summary: N files → bundled/, M files → local/
```

### Safety rules
- If `profile_groups.json` is missing or unreadable: log a warning, abort migration, leave files flat. App continues to work (fails open).
- If a file move fails: log the error, continue with remaining files. Do not abort.
- Only moves direct children of `profiles/` — does not touch files already in subdirectories.
- If bundled already has the file (written by entrypoint), discard the flat version rather than overwriting the image version.

### Called from
`main.py` module level, before the FastAPI app starts serving requests.

---

## Entrypoint change (`docker/entrypoint.sh`)

```bash
# Before
cp -n "${profile}" "${profile_dir}/"

# After
mkdir -p "${profile_dir}/bundled"
cp -f "${profile}" "${profile_dir}/bundled/"
```

`cp -f` is safe because `bundled/` is exclusively image-managed.

---

## API changes (`aquila_web/main.py`)

### `list_profiles()`

- `rglob("*.json")` already descends into both subdirs automatically
- Device filter works correctly: `"bundled" in path.parts` is now true for production paths
- Deduplication: collect filenames seen in `local/` first; when iterating `bundled/`, skip any filename already in the local set
- Return order: local profiles first, then bundled

### Profile save (`POST /profiles`)

- If `profile_id` resolves to a path inside `profiles/bundled/`: return `403 Forbidden` — bundled profiles cannot be edited
- New profiles always written to `profiles/local/`

```python
if "bundled" in profile_path.parts:
    raise HTTPException(status_code=403, detail="Bundled profiles are read-only.")
profile_path = profile_dir / "local" / f"{file_name}.json"
```

Ensure `local/` is created if it doesn't exist.

### Profile delete (`POST /profiles/delete`)

- If profile path is inside `profiles/bundled/`: return `403 Forbidden`

```python
if "bundled" in profile_path.parts:
    raise HTTPException(status_code=403, detail="Bundled profiles cannot be deleted.")
```

### `resolve_profile_dir()` — no change

Returns `/opt/aquila/profiles/` as before.

### `resolve_device_profiles()` — no change

Already correct. Filter in `list_profiles()` now works because path genuinely contains `bundled`.

---

## Frontend changes

### Profile list page (`profiles.html` / profiles JS)

- For each profile returned by `/profiles`, the API response includes a new field: `"bundled": true/false`
- Bundled profiles display a **lock icon** next to the profile name in the profile list page only (not in the run screen dropdown)
- Lock icon is purely visual — no tooltip or explanation needed for now
- Edit and Delete buttons are hidden (or disabled) for bundled profiles in the list UI

### Run screen dropdown — no change

Profile names appear identically in the dropdown regardless of bundled/local. No lock icon there.

---

## `/profiles` response shape change

Add `bundled` boolean to each profile entry:

```json
{
  "id": "bundled/ABBA_ramp1.75_EA30.json",
  "name": "ABBA ramp 1.75 EA30",
  "bundled": true,
  ...
}
```

---

## Files touched

| File | Change |
|---|---|
| `docker/entrypoint.sh` | Write to `profiles/bundled/`, use `cp -f`, `mkdir -p bundled` |
| `aquila_web/main.py` | `_migrate_profiles()` at startup; save/delete blocked on bundled; `bundled` field in response; local/ as save target |
| `aquila_web/static/profiles/index.html` or profiles JS | Lock icon on bundled profiles; hide edit/delete for bundled |
| `unit_tests/test_device_profile_filtering.py` | Migration logic, filter, 403 responses, deduplication |

No changes to `device_profiles.json`, `profile_groups.json`, Dockerfile, or docker-compose.

---

## Terminal workflow for customizing a bundled profile

```bash
# On the device
cp /opt/aquila/profiles/bundled/ABBA_ramp1.75_EA30.json \
   /opt/aquila/profiles/local/ABBA_custom.json

# Edit the local copy
nano /opt/aquila/profiles/local/ABBA_custom.json
```

The custom version appears in the UI as a normal editable profile. The bundled original remains untouched and continues to update with new images.

---

## What stays the same for users

- All profiles appear in one combined list — no separate sections
- Run screen dropdown is unchanged
- Device filtering behavior is unchanged in intent; this fixes it so it actually works in production
- Bundled profiles update automatically with new images
- User-created profiles are never touched by updates
