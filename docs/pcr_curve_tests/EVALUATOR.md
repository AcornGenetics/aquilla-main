# PCR Curve Evaluator

## Overview
`pcr_curve_tests/evaluator.py` centralizes the curve checks into reusable functions. The pytest tests now call these functions, and the runtime detection pipeline can reuse the same logic without invoking pytest.

## Key Functions
- `evaluate_curve(curve, log_name, dye, well)` returns a status (`detected`, `undetected`, or `inconclusive`) plus per-check results.
- `check_*` helpers implement each PCR curve check and return `True`/`False`.

## Detection Integration
`aq_curve/curve.py` now calls `evaluate_curve` inside `results_to_json` before using `is_detected`:

- If the threshold check fails: status becomes **Not Detected**.
- If the threshold check passes but any other check fails: status becomes **Inconclusive**.
- If all checks pass: `is_detected` decides **Detected** vs **Not Detected**.

This preserves the existing `is_detected` behavior while incorporating the PCR curve QC checks.
