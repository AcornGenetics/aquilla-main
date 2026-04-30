# ADR-008: PCR Curve Analysis as a Post-Run Processing Pipeline

**Status**: Accepted  
**Date**: 2026-04-30  
**Deciders**: Aquila Engineering Team

## Context

PCR optical data is collected every cycle during a run. Analysis (baseline subtraction, Cq detection, curve validation) could run either in real-time during the run or as a batch step after the run completes. The choice affects UI responsiveness, hardware load, and result reproducibility.

## Decision

PCR curve analysis runs as a **post-run pipeline** triggered after the thermal profile completes. Raw ADC data is written to `/opt/aquila/logs/results/` during the run. After run completion, `aq_curve/analysis_service.py` loads the raw data, applies baseline correction and crosstalk subtraction (matrix-based), computes Cq values via the `Curve` class, validates quality metrics via `Evaluator`, and writes a JSON results file + PNG plots.

The FastAPI `/results/{run_id}` endpoint reads these files on demand.

## Consequences

**Positive**
- Hardware loop is not blocked by analysis computation; thermal control runs at full precision.
- Analysis parameters (threshold, baseline window, crosstalk matrix) can be tuned and re-run on historical data without re-running the hardware.
- Results are reproducible: the same raw data always produces the same analysis output.
- PNG plots can be regenerated without hardware.

**Negative**
- Results are not available until after run completion; operators cannot see Cq values during the run.
- Raw data files must be reliably written during the run; a crash mid-run may produce incomplete data.
- Post-run analysis adds latency between "run done" and "results available"; for short profiles this is negligible.

## Alternatives Considered

- **Real-time streaming analysis**: provides live Cq estimates but requires analysis to keep up with thermal cycle rate; risks blocking hardware loop.
- **On-device ML inference**: could detect early stop conditions but adds model management complexity.
- **Cloud-offloaded analysis**: adds network dependency; inappropriate for offline/lab use.
