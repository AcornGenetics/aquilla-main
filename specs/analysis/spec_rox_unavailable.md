# Spec: ROX Unavailable Mode

## Summary

A per-profile flag (`rox_unavailable`) that suppresses all ROX analysis and display. When active:
- The ROX (right) half of every result dot is permanently grey — no status color, ever.
- The results table ROX row cells read `"ROX Unavailable"` instead of a detection result.
- No ROX curve evaluation runs.

---

## Profile JSON

Add a top-level boolean to the profile file:

```json
{
  "title": "My Profile",
  "rox_unavailable": true,
  "labels": { "fam": "Target" }
}
```

`rox_unavailable` lives at the top level, not inside `labels`. It is absent (or `false`) for normal profiles — no default needed.

---

## Backend changes

### `sentri_web/main.py`

**`_load_profile_labels`** — already returns the `labels` dict. Rename or extend it to also surface the flag:

```python
def _load_profile_config(profile_name: str | None) -> dict:
    # returns {"labels": {...}, "rox_unavailable": bool}
```

Or keep `_load_profile_labels` as-is and add a separate `_profile_rox_unavailable(profile_name)` helper — whichever keeps the diff smaller.

The flag must reach `process_run` so pass it alongside `labels`:

```python
labels = _load_profile_labels(profile_name)
rox_unavailable = _profile_rox_unavailable(profile_name)
_analysis.process_run(..., labels=labels, rox_unavailable=rox_unavailable)
```

**`/profiles/details`** — include the flag in the response so the frontend can read it on profile select:

```python
return {
    "id": ...,
    "title": ...,
    "labels": data.get("labels", {}),
    "rox_unavailable": bool(data.get("rox_unavailable", False)),
    "steps": ...,
}
```

### `sentri_curve/analysis_service.py`

Accept and forward the flag:

```python
def process_run(self, optics_path, results_filename, plot_path, labels=None, rox_unavailable=False):
    curve = Curve(src_basedir=self._results_dir)
    curve.results_to_json(optics_path, results_filename, rox_unavailable=rox_unavailable)
    generate_optics_plot(optics_path, plot_path, labels=labels)
```

### `sentri_curve/curve.py` — `results_to_json`

Accept `rox_unavailable=False`. When true, replace the rox block with a constant — no `evaluate_curve` call, no `resolve_cq` call:

```python
def results_to_json(self, raw_logfile, results_logfile, rox_unavailable=False):
    ...
    ROX_UNAVAILABLE = "ROX Unavailable"

    rox_row = (
        {str(w): ROX_UNAVAILABLE for w in [1, 2, 3, 4]}
        if rox_unavailable
        else {
            "1": resolve_status(1, "rox", 1),
            "2": resolve_status(1, "rox", 2),
            "3": resolve_status(1, "rox", 3),
            "4": resolve_status(1, "rox", 4),
        }
    )

    rox_cq_row = (
        {str(w): None for w in [1, 2, 3, 4]}
        if rox_unavailable
        else { ... existing cq calls ... }
    )
```

---

## Frontend changes

### `sentri_web/static/script.js`

Add a module-level flag alongside `dyeLabels`:

```js
let roxUnavailable = false;
```

In `applyDyeLabels`, accept and store it:

```js
const applyDyeLabels = (labels = {}, isRoxUnavailable = false) => {
    dyeLabels = { fam: labels.fam || DEFAULT_DYE_LABELS.fam, rox: labels.rox || DEFAULT_DYE_LABELS.rox };
    roxUnavailable = isRoxUnavailable;
    if (typeof loadResults === "function") loadResults();
};
```

In `loadProfileLabels`, pass it through from the `/profiles/details` response:

```js
applyDyeLabels(data.labels || {}, Boolean(data.rox_unavailable));
```

In `setHalfStatus`, add an `is-unavailable` class path:

```js
const setHalfStatus = (halfEl, value, forceUnavailable = false) => {
    if (!halfEl) return;
    halfEl.classList.remove("is-detected", "is-inconclusive", "is-not-detected", "is-unavailable");
    if (forceUnavailable) {
        halfEl.classList.add("is-unavailable");
        return;
    }
    if (value === "Detected") halfEl.classList.add("is-detected");
    else if (value === "Inconclusive") halfEl.classList.add("is-inconclusive");
    else if (value) halfEl.classList.add("is-not-detected");
};
```

In the dot-rendering loop, pass the flag for the rox half:

```js
setHalfStatus(famHalf, famStatus);
setHalfStatus(roxHalf, roxStatus, roxUnavailable);
```

The `tubeDetected` / `tubeInconclusive` summary loop (`["1", "2"].forEach`) must skip row `"2"` when `roxUnavailable` is true, so a ROX-unavailable profile doesn't count `"ROX Unavailable"` as an undetected result toward the dot's overall status class.

### `sentri_web/static/styles.css`

Add after the existing `.results-dot__half.is-inconclusive` rule:

```css
.results-dot__half.is-unavailable {
  background-color: #d1d5db;
}
```

`#d1d5db` matches the dot border color, so the grey half reads as neutral/absent rather than a status.

---

## Reset behavior

`resetResultsUI` (called on new run / clear) already strips `is-detected`, `is-not-detected`, `is-inconclusive` from all halves. Add `is-unavailable` to that removal set — then `loadResults` re-applies it immediately from `roxUnavailable`, so the grey half reappears on the next render cycle.

---

## Files touched

| File | Change |
|---|---|
| Profile JSON(s) | Add `"rox_unavailable": true` |
| `sentri_web/main.py` | Helper for flag; pass to `process_run`; include in `/profiles/details` |
| `sentri_curve/analysis_service.py` | Accept + forward `rox_unavailable` param |
| `sentri_curve/curve.py` | `results_to_json` skips rox eval; writes `"ROX Unavailable"` |
| `sentri_web/static/script.js` | Module flag; `applyDyeLabels`; `setHalfStatus`; dot loop; reset |
| `sentri_web/static/styles.css` | `.is-unavailable` rule |

---

## What does NOT change

- FAM analysis is unaffected.
- The ROX column header in the results table still shows the profile's `rox` label (or "ROX" default) — the cell values are what say "ROX Unavailable". Alternatively suppress the row header too — TBD by UX preference.
- No new API endpoints needed.
- History entries store the raw results JSON, so replaying history also shows grey halves (because the stored value is `"ROX Unavailable"` and the frontend flag is re-set from the current profile, not the stored run — clarify if history replay needs to handle this independently).
