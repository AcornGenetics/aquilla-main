# Repo Refactor Plan

Goal: clean up the root folder, consolidate tests into one tree, and move all
files into logical homes. No `src/` layout — this is in-place device code.

---

## Target Structure

```
aquilla-main/
├── application.py          # assay loop entry point
├── state_run_assay.py      # state machine (imported by application.py)
├── config.py               # config loader
├── config.json             # hardware config
├── README.md
├── CLAUDE.md
├── AGENTS.md
├── pytest.ini
├── requirements*.txt
├── .gitignore
├── .dockerignore
│
├── aq_lib/                 # hardware control library
│   ├── fan_class.py        # ← from root
│   ├── led_class.py        # ← from root
│   ├── adc_class.py        # ← from root
│   └── (existing files unchanged)
│
├── aq_curve/               # PCR analysis (unchanged)
│
├── aquila_web/             # FastAPI app + UI (unchanged)
│
├── profiles/
│   └── bundled/            # production profiles only — delete old test JSONs
│
├── config_files/           # runtime config templates (unchanged)
│   └── aquila_app.service  # ← from root
│
├── docker/                 # Docker assets (unchanged)
│
├── fleet-config/           # fleet deploy config (unchanged)
│
├── scripts/
│   ├── deploy/             # ← deployment scripts from root
│   │   ├── deployment1.sh
│   │   ├── deployment2.sh
│   │   ├── deployment2_verify.sh
│   │   ├── exit_kiosk.sh
│   │   ├── update_kiosk_x11.sh
│   │   └── update.sh
│   ├── hardware/           # ← GPIO/serial debug scripts from root + mini-dirs
│   │   ├── test_axis.py
│   │   ├── test_drawer.py
│   │   ├── test_fan.py
│   │   ├── test_connection.py
│   │   ├── test_lm35.py
│   │   ├── test_positions.py
│   │   ├── test_exit.py
│   │   ├── toggle_pin.py
│   │   ├── motor_disable.py
│   │   ├── get_params.py
│   │   ├── optics_read.py
│   │   ├── pcr_meer_off.py
│   │   ├── led_off.py
│   │   ├── led_on.py
│   │   ├── adc/            # ← from root
│   │   ├── led/            # ← from root
│   │   ├── beam_breaks/    # ← from root
│   │   └── motor_test/     # ← from root
│   ├── hardware tests/     # ← sequenced hardware verification scripts
│   │   ├── led_current_verification.py   # run back to back with FAM / ROX
│   │   ├── raster_detailed_log_centered.py  # run back to back with TE blanks of FAM / ROX
│   │   ├── motor_drawer.py
│   │   ├── motor_axis.py
│   │   ├── test_adc4_logged.py
│   │   ├── run_lid_heater.py
│   │   └── lod_verification_all.py
│   ├── tools/              # ← research & analysis scripts from root
│   │   ├── PCR_plot.py
│   │   ├── Raster.py
│   │   ├── diagnostic_sweep.py
│   │   ├── melt_curve.py
│   │   ├── convert_results_to_fake_run.py
│   │   └── meer_ss.py
│   └── setup/              # (already exists, unchanged)
│
├── tests/                  # ALL pytest tests (single tree)
│   ├── conftest.py
│   ├── contract/           # API endpoint tests (FastAPI TestClient)
│   │   └── test_bundled_profiles.py   # ← from root
│   ├── integration/        # simulated full runs (DEV_SIMULATE=1)
│   ├── state/              # state machine safety tests
│   ├── unit/               # ← merge of unit_tests/ + root unit tests
│   │   ├── test_force_stop.py
│   │   ├── test_meer_log_stop.py
│   │   ├── test_results_to_json_path.py
│   │   ├── test_curve.py               # ← from root
│   │   ├── test_result_consistency.py  # ← from root
│   │   └── test_state_request.py       # ← from root
│   ├── pcr_curve/          # ← merge of pcr_curve_tests/
│   │   └── test_baseline_length.py, etc.
│   ├── e2e/
│   └── fleet_device/
│
└── docs/                   # all documentation
    ├── refactor-plan.md    # this file
    ├── deployment/
    ├── deployment.txt      # ← from root
    ├── deployment1.txt     # ← from root
    ├── deployment2_plan.md # ← from root
    ├── deployment2_tests.md# ← from root
    ├── device-log-plan.md  # ← from root
    ├── kiosk-touch-fix.md  # ← from root
    ├── wifi-config.md      # ← from root
    └── update.txt          # ← from root
```

---

## Phases

### Phase 1 — Docs & scripts (no code changes, no import changes)
Move files only. Zero risk.

| Action | Files |
|--------|-------|
| Move to `docs/` | `deployment.txt`, `deployment1.txt`, `deployment2_plan.md`, `deployment2_tests.md`, `device-log-plan.md`, `kiosk-touch-fix.md`, `wifi-config.md`, `update.txt` |
| Move to `scripts/deploy/` | `deployment1.sh`, `deployment2.sh`, `deployment2_verify.sh`, `exit_kiosk.sh`, `update_kiosk_x11.sh`, `update.sh` |
| Move to `scripts/hardware/` | `test_axis.py`, `test_fan.py`, `test_drawer.py`, `test_connection.py`, `test_lm35.py`, `test_positions.py`, `test_exit.py`, `toggle_pin.py`, `motor_disable.py`, `get_params.py`, `optics_read.py`, `pcr_meer_off.py`, `led_off.py`, `led_on.py`, `adc/`, `led/`, `beam_breaks/`, `motor_test/` |
| Move to `scripts/hardware tests/` | `led_current_verification.py` (run back to back with FAM/ROX), `raster_detailed_log_centered.py` (run back to back with TE blanks of FAM/ROX), `motor_drawer.py`, `motor_axis.py`, `test_adc4_logged.py`, `run_lid_heater.py`, `lod_verification_all.py` |
| Move to `scripts/tools/` | `PCR_plot.py`, `Raster.py`, `diagnostic_sweep.py`, `melt_curve.py`, `convert_results_to_fake_run.py`, `meer_ss.py` |
| Move to `config_files/` | `aquila_app.service` |
| Delete | `cmdline.txt`, `config.txt` (device-local, gitignored, never needed in repo) |
| Delete | `ruvector.db` (runtime DB, gitignored) |
| Decide | `compose.yaml` — NOT a duplicate of `docker/docker-compose.yml`; it uses `build: context: .` for local dev while the docker/ version pulls a registry image. Keep if local `docker compose up` is needed; delete only if the team has fully migrated to the fleet image workflow. |

### Phase 2 — Consolidate tests (pytest.ini update only)
Move test files, update `pytest.ini`. No production code changes.

| Action | Files |
|--------|-------|
| Move to `tests/contract/` | `test_bundled_profiles.py` |
| Move to `tests/unit/` | contents of `unit_tests/`, `test_curve.py`, `test_result_consistency.py`, `test_state_request.py` |
| Move to `tests/pcr_curve/` | contents of `pcr_curve_tests/` |
| Delete dirs | `unit_tests/`, `pcr_curve_tests/` |
| Update `pytest.ini` | `testpaths = tests` (single entry) |

### Phase 3 — Move class files into `aq_lib/` (15 import changes across 13 files)
Move `fan_class.py`, `adc_class.py`, `led_class.py` into `aq_lib/`.

**Import changes required:**

| File | Old import | New import |
|------|-----------|-----------|
| `state_run_assay.py:31` | `from fan_class import Fan` | `from aq_lib.fan_class import Fan` |
| `state_run_assay.py:32` | `from adc_class import OpticalRead` | `from aq_lib.adc_class import OpticalRead` |
| `tests/unit/hardware/test_fan.py:53` | `if "fan_class" in sys.modules:` | `if "aq_lib.fan_class" in sys.modules:` |
| `tests/unit/hardware/test_fan.py:55` | `importlib.import_module("fan_class")` | `importlib.import_module("aq_lib.fan_class")` |
| `led_off.py:3` | `from led_class import LED` | `from aq_lib.led_class import LED` |
| `led_on.py:3` | `from led_class import LED` | `from aq_lib.led_class import LED` |
| `optics_read.py:36` | `from adc_class import OpticalRead` | `from aq_lib.adc_class import OpticalRead` |
| `optics_read.py:37` | `from led_class import LED` | `from aq_lib.led_class import LED` |
| `diagnostic_sweep.py:30` | `from adc_class import OpticalRead` | `from aq_lib.adc_class import OpticalRead` |
| `diagnostic_sweep.py:31` | `from led_class import LED` | `from aq_lib.led_class import LED` |
| `test_adc4_logged.py:2` | `from adc_class import OpticalRead` | `from aq_lib.adc_class import OpticalRead` |
| `test_adc4_logged.py:7` | `from led_class import LED` | `from aq_lib.led_class import LED` |
| `lod_verification_all.py:2` | `from adc_class import OpticalRead` | `from aq_lib.adc_class import OpticalRead` |
| `lod_verification_all.py:3` | `from led_class import LED` | `from aq_lib.led_class import LED` |
| `Raster.py:2` | `from adc_class import OpticalRead` | `from aq_lib.adc_class import OpticalRead` |
| `Raster.py:8` | `from led_class import LED` | `from aq_lib.led_class import LED` |
| `raster_detailed_log_centered.py:2` | `from adc_class import OpticalRead` | `from aq_lib.adc_class import OpticalRead` |
| `raster_detailed_log_centered.py:8` | `from led_class import LED` | `from aq_lib.led_class import LED` |
| `test_lm35.py:3` | `from adc_class import OpticalRead` | `from aq_lib.adc_class import OpticalRead` |
| `led_current_verification.py:2` | `from adc_class import OpticalRead` | `from aq_lib.adc_class import OpticalRead` |
| `led_current_verification.py:3` | `from led_class import LED` | `from aq_lib.led_class import LED` |
| `melt_curve.py:18` | `from fan_class import Fan` | `from aq_lib.fan_class import Fan` |
| `melt_curve.py:19` | `from adc_class import OpticalRead` | `from aq_lib.adc_class import OpticalRead` |

Note: line numbers above reflect pre-move positions. After files are relocated to `scripts/hardware/` and `scripts/tools/`, the import paths change but the fix is the same.

### Phase 4 — Clean profiles/
Delete old test/dev profile JSONs from `profiles/` root. Only `profiles/bundled/` should contain files.

| Action | Files |
|--------|-------|
| Delete | `12NOV_acorn_pcr.json`, `25NOV_acorn_pcr.json`, `60C_95C.json`, `SN001_strat_sybr.json`, `SN002_dwell_test.json`, `SN002_strat_sybr.json`, `SN01_acorn_pcr.json`, `acorn_pcr_profile.json`, `joel_test.json`, `melt_curve.json`, `ryan_profile_12NOV.json`, `ryan_short.json` |
| Decide | `ryan_profile.json` — keep or delete? |

---

## Import Impact Summary

- **Phase 1**: zero import changes
- **Phase 2**: zero import changes
- **Phase 3**: 23 lines changed across 13 files
- **Phase 4**: zero import changes

---

## Verification after each phase

```bash
# After Phase 2 — confirm all tests still discovered and passing
pytest tests -v

# After Phase 3 — confirm production imports resolve
python -c "from aq_lib.fan_class import Fan; print('ok')"
python -c "from aq_lib.adc_class import OpticalRead; print('ok')"
pytest tests -v
```
