# Repository Guidelines

## Project Structure & Module Organization
- `aq_lib/` holds the core hardware-control drivers and helpers (motors, TEC, lid heater, state requests).
- `aq_curve/` contains PCR curve analysis and results processing utilities.
- `aquila_web/` is the FastAPI backend plus `aquila_web/static/` for the no-build HTML/CSS/JS UI.
- Tests live in `unit_tests/` and `pcr_curve_tests/`, with additional standalone diagnostics at the repo root (e.g., `test_axis.py`).
- Configuration and data live in `config_files/`, `profiles/`, `data/`, and `logs/`.
- `docker/` and `docs/` capture container assets and internal documentation.

## Build, Test, and Development Commands
- `python -m pip install -r requirements.txt` installs backend dependencies.
- `python application.py` runs the main CLI assay loop (hardware required).
- `uvicorn main:app --reload --host 127.0.0.1` from `aquila_web/` starts the FastAPI UI backend.
- `streamlit run PCR_plot.py` launches the plotting dashboard.
- `docker compose -f docker/docker-compose.yml up --build` runs backend, UI, and streamlit containers.

## Coding Style & Naming Conventions
- Python follows 4-space indentation, `snake_case` for functions/variables, and `CapWords` for classes.
- Module and script names are lowercase with underscores (e.g., `state_run_assay.py`).
- Frontend assets are plain HTML/CSS/JS; keep selectors consistent and bump the `?v=` cache key when editing.

## Testing Guidelines
- Tests use `pytest` (see `requirements.txt`).
- Naming convention is `test_*.py`, organized under `unit_tests/` and `pcr_curve_tests/`.
- Hardware- or log-dependent tests should be run selectively (e.g., `pytest pcr_curve_tests`).

## UI Run-State Notes
- UI state comes from `config_files/state_config.json` via `/change_screen/` and the `/ws` websocket.
- The run page uses `aquila_web/static/script.js` to toggle sections and the Done modal; `/run/complete/ack` resets the server screen to `ready`.
- The assay loop (`application.py` → `state_run_assay.py`) holds the `complete` screen until the next button action.
- End-of-run now forces `screen=complete` as soon as results/logging finish, independent of drawer buttons.
- Drawer open/close no longer changes screens during `end` state, so Done/results aren't retriggered.
- `run_complete_ack` now propagates through `/button_status` so the assay loop can advance to `ready` after the modal is dismissed.
- The Done modal now includes a `Reset to Ready` button that clears the modal and returns the run UI to the ready state.
- Simulated runs now wait for `run_complete_ack` before returning to `ready`, matching non-simulated behavior.
- Results now persist until reset; `/results/clear` is only triggered by the Reset button.
- `/results` now falls back to the latest history entry if the in-memory path is missing, and the UI shows “Error in results path” when the results file cannot be loaded.
- Legacy `ready.html` and `complete.html` screens now include a Reset button.
- On-screen keyboard is provided by `aquila_web/static/keyboard.js` and wired into Run/Login/Profile edit pages for kiosk use.
- History summaries now resolve absolute `results_path` so the History page matches Run results for new runs.
- Deployment/update scripts now enforce LightDM autologin (`rpd-x`) and append X11 rotation (`xrandr`) for kiosk setups.

## Kiosk Rotation Notes
- `update.sh` reboots automatically after finishing.
- Default rotation uses `ROTATE_OUTPUT=HDMI-2` and `ROTATE_DIR=left`; override with env vars as needed (e.g., `ROTATE_OUTPUT=HDMI-2 ROTATE_DIR=normal ./update.sh`).
- Rotation setup creates `/etc/xdg/openbox/autostart` if missing and updates/sets the `xrandr --output ... --rotate ...` line for X11 GUI rotation.

## Commit & Pull Request Guidelines
- Recent history uses short, lowercase, present-tense messages (e.g., "update", "more fixes"); keep commits concise and scoped.
- PRs should include a clear summary, testing notes (`pytest ...` or "not run"), and UI screenshots when applicable.

## Configuration & Hardware Notes
- Runtime settings live in `config_files/` and `profiles/`; Docker uses env vars like `DEVICE_ID` and `RUN_MODE`.
- Many scripts expect connected devices (`/dev/ttyACM0`, GPIO, I2C/SPI). Call out hardware assumptions in PRs.

## Change Log
- Updated `aquila_web/static/keyboard.js` to avoid double input on kiosks by using pointer handling with touch/mouse suppression, and bumped keyboard cache keys to `?v=5` in login/run/profile pages.
- Added global tap highlight suppression and focus-state overrides in `aquila_web/static/styles.css` with cache-key bumps across UI pages to reduce touch flashes.
- Updated tap highlight suppression with nav-specific rules for kiosk links.
- For kiosk-only navigation, a `pointerdown` handler that prevents default link behavior can be used to avoid tap flashes; note this disables keyboard navigation and long-press link actions, so it should stay kiosk-only.
- Added a Run-only Stop Run button plus backend stop requests, safe abort handling, and force-stop tests in `unit_tests/test_force_stop.py`.
