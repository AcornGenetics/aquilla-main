# Spec: Per-Device Profile Filtering

## Problem

All bundled profiles in `profiles/bundled/` are currently available to every device. There is no way to restrict which profiles appear on a given device without physically removing files from the image.

## Solution

Two new config files baked into the image control which profiles each device sees. The device queries its own hostname at runtime, looks itself up, and the API filters the profile list accordingly.

---

## New Files

### `config_files/profile_groups.json`

Defines named groups of profiles. Edit this file to add new groups or add a profile filename to an existing group.

```json
{
    "full": null,
    "verification_only": [
        "verification_profile.json"
    ],
    "abba": [
        "ABBA_ramp1.75_EA30.json",
        "verification_profile.json"
    ],
    "hygiena": [
        "Hygiena_ramp1.75_EA30.json",
        "verification_profile.json"
    ],
    "abba_hygiena": [
        "ABBA_ramp1.75_EA30.json",
        "Hygiena_ramp1.75_EA30.json",
        "verification_profile.json"
    ]
}
```

- `null` means all profiles (same as no restriction)
- Profile filenames must match the actual `.json` filenames in `profiles/bundled/`

---

### `config_files/device_profiles.json`

Maps each device hostname to a group. This is the **primary file to edit day-to-day**.

```json
{
    "sn02": {
        "profile_group": "verification_only"
    },
    "sn07": {
        "profile_group": "abba_hygiena"
    },
    "sn12": {
        "profile_group": "abba",
        "extra_profiles": ["ryan_thermal_tests.json"]
    },
    "sn99": {
        "profile_group": "full"
    }
}
```

**Fields:**

| Field | Required | Description |
|---|---|---|
| `profile_group` | Yes | Must match a key in `profile_groups.json` |
| `extra_profiles` | No | Additional profile filenames added on top of the group |

**Fallback:** If a device hostname is not present in this file, it gets all profiles. No error is raised.

---

## Modified File

### `sentri_web/main.py`

#### New function: `resolve_device_profiles() -> set[str] | None`

Reads the two config files and returns the set of allowed profile filenames for the running device.

Resolution logic:
1. Read hostname from `DEVICE_HOSTNAME` env var, fall back to `socket.gethostname()`
2. Load `config_files/device_profiles.json`
3. If hostname not found → return `None` (no restriction)
4. Load `config_files/profile_groups.json`, look up the device's `profile_group`
5. If group value is `null` → return `None` (no restriction)
6. Start with the group's filename list
7. Append any `extra_profiles` from the device entry
8. Return as `set[str]`

If either config file is missing or malformed, log a warning and return `None` (fail open — device sees all profiles rather than none).

#### Modified function: `list_profiles()` (line 898)

One filter added before appending each profile to the result list:

```python
allowed = resolve_device_profiles()
if allowed is not None and path.name not in allowed:
    continue
```

Nothing else in `list_profiles()` changes.

---

## What Does Not Change

| Component | Reason |
|---|---|
| `host_config.json` | Hardware config only, written by `deployment2.sh` |
| `deployment2.sh` | No changes needed |
| Docker volumes / mounts | No changes |
| Profile execution once selected | Filtering is list-only |
| User-created profiles | Live in `/opt/aquila/profiles/` on device disk, always visible to that device |
| `profile_config.json` | Superseded by `profile_groups.json`; can be removed separately |

---

## Deployment Flow

Both new files are baked into the image via the existing `COPY . .` in `docker/Dockerfile.api`. No Dockerfile changes needed.

| Goal | What to edit |
|---|---|
| Add a new bundled profile file | Add to `profiles/bundled/`, add filename to relevant group(s) in `profile_groups.json` |
| Give a device a different set | Change its `profile_group` in `device_profiles.json` |
| Add one profile to one device | Add filename to `extra_profiles` in `device_profiles.json` |
| Create a new group | Add entry to `profile_groups.json`, assign devices to it |
| Remove a profile from all devices | Remove filename from all groups in `profile_groups.json` |

All changes → merge to `main` → CI builds image → Watchtower delivers to fleet within ~5 minutes.

---

## Transparency Script

### `scripts/profile_map.py`

A read-only CLI script that prints a clear view of which profiles are assigned to which devices. It reads live data directly from `config_files/device_profiles.json` and `config_files/profile_groups.json` at runtime — the output always reflects the actual current state of those files, not hardcoded values.

**Default output (all devices):**

```
$ python scripts/profile_map.py

Device    Group               Profiles
────────────────────────────────────────────────────────────────
sn02      verification_only   verification_profile.json
sn07      abba_hygiena        ABBA_ramp1.75_EA30.json
                              Hygiena_ramp1.75_EA30.json
                              verification_profile.json
sn12      abba                ABBA_ramp1.75_EA30.json
          + extra             ryan_thermal_tests.json
                              verification_profile.json
sn99      full                (all profiles)
```

(Above is illustrative of the format — actual rows and profile names come from the live config files.)

**Flags:**

| Flag | Description |
|---|---|
| `--device sn12` | Show only one device |
| `--profile ABBA_ramp1.75_EA30.json` | Show all devices that have a given profile |
| `--group abba` | Show all devices assigned to a group |

**Location:** `scripts/profile_map.py`

**Dependencies:** stdlib only (`json`, `argparse`) — no pip installs required.

---

## Tests to Add

| Test | Expected behaviour |
|---|---|
| `resolve_device_profiles()` — hostname not in `device_profiles.json` | Returns `None` |
| `resolve_device_profiles()` — group is `null` | Returns `None` |
| `resolve_device_profiles()` — known hostname with group | Returns correct set of filenames |
| `resolve_device_profiles()` — `extra_profiles` present | Returned set includes group filenames plus extras |
| `resolve_device_profiles()` — config file missing | Returns `None`, logs warning |
| `GET /profiles` — allowlist active | Only allowed profiles returned |
| `GET /profiles` — device not in `device_profiles.json` | All profiles returned |
