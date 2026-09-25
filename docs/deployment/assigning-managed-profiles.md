# Assigning Managed Profiles (AWS Console)

How to push a Profile to a specific Sentri from AWS — no device access needed.

- Region `us-east-2`, account `867958227555`.
- Prereq: the device is already onboarded (see
  [`greengrass-device-setup.md`](./greengrass-device-setup.md)) and its ring deployment
  carries `com.acorn.profile-sync`.

---

## How it works (30 seconds)

A Sentri has three profile sources on disk: `bundled/` (baked into the app image),
`local/` (made on the device), and **`managed/`** (assigned centrally — this guide).

Managed Profiles are **decoupled from the release** (ADR-0002): you assign them per
device through the Thing's **`profiles` named Device Shadow**, and the on-device
`com.acorn.profile-sync` component pulls the content from **S3** into
`/opt/aquila/profiles/managed/`. Assign = add an S3 key to the shadow's `desired`;
detach = remove it.

```
 you: upload JSON → S3 (profiles/…)      you: add key to `profiles` shadow desired
                         │                              │
                         ▼                              ▼
        ShadowManager syncs desired down  →  agent fetches from S3  →  managed/  →  app
```

---

## 1. Upload the profile to S3

**S3 console** → bucket `acorn-fleet-deviceaccess-artifactsbucket…` → open the
**`profiles/`** folder → **Upload** → add the `.json`.

- The final object key must be **`profiles/<name>.json`** (i.e. inside the `profiles/`
  folder).
- Re-uploading the same key updates the profile in place; the version marker changes and
  every device with it assigned re-pulls it on the next sync.

---

## 2. Assign it to a device via the shadow

**IoT Core → Manage → All devices → Things** → select the Thing (its name is the Device
ID) → **Device Shadows** tab.

> The console **defaults to the Classic Shadow** — you must click into the **`profiles`**
> named shadow, or it looks empty. If there isn't one yet:
> **Create Shadow → Named shadow → name it `profiles` → Create**.

Open **`profiles`** → **Edit** → set the **desired** state, then **Update**:

```json
{ "state": { "desired": { "profiles": [ "profiles/<name>.json" ] } } }
```

Assign more than one by listing more keys:

```json
{ "state": { "desired": { "profiles": [
  "profiles/ryan_thermal_tests.json",
  "profiles/Beer_Spoilers_Bacteria_tester.json"
] } } }
```

⚠️ **Each key must include the `profiles/` prefix and match the S3 object exactly.** A
wrong or prefix-less key currently **wedges the whole sync for that device** — nothing
lands until it's corrected. Double-check spelling against Step 1.

---

## 3. Confirm it landed

- **Console:** the same **`profiles`** shadow — the **reported** state grows to include
  `{"name": "...", "version": "..."}` for each delivered profile. When **reported**
  mirrors **desired**, it's on the device. Expect this within **≤5 min** (ShadowManager
  syncs `desired` down in seconds; the agent polls every **300 s**).
- **Device app UI:** the on-device profiles screen fetches its list **only on page load**
  — **reload** the screen to see a newly-synced profile. Look for the profile's **title**
  (from the JSON), not its filename.

---

## 4. Detach a profile

Edit the `profiles` shadow and **remove** the key from `desired.profiles` → **Update**.
The agent deletes the local file on its next poll. Removing every key (`"profiles": []`)
detaches all managed profiles from that device.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `reported` never catches up to `desired` (stays empty) | Shadow cloud-sync is 403ing — the device cert isn't authorized to sync its shadow, or the policy changed and the device hasn't reconnected. See Appendix A in [`greengrass-device-setup.md`](./greengrass-device-setup.md#appendix-a--shadow-sync-authorization-background); quick fix: `ssh pi@<device> sudo systemctl restart greengrass`. |
| One profile assigned, the whole device stops syncing | A bad S3 key (wrong/missing `profiles/` prefix, typo) wedges the reconcile. Fix the key in the shadow. |
| Profile on disk but not in the app list | The UI only loads the list on page open — reload the profiles screen. |
| Nothing ever lands, device otherwise healthy | The device's ring deployment doesn't include `com.acorn.profile-sync`. Move it to a ring that does. |
| Can't find the `profiles` shadow | You're on the Classic Shadow — switch to the named shadow `profiles` (create it if absent). |
