# Python Files Overview

## adc Core
- `adc_class.py`: Implements the `OpticalRead` class that configures the AD7124 ADC, sets LED GPIO polarity from config, and logs fluorescence readings alongside LED states during capture cycles.
- `adc/adc_monitor.py`: Continuously polls the AD7124 while jogging GPIO LEDs and prints multiple low-pass filtered voltage streams for long-term stability monitoring.
- `adc/adc_spi_test.py`: Minimal SPI smoke test that opens `/dev/spidev0.0`, reads the AD7124 ID register, and reports the result to confirm wiring.
- `adc/adc_test.py`: Blinks LED 27 in fixed slots and captures alternating AD7124 readings so you can compare on/off voltages and noise.
- `adc/adc_test2.py`: Alternative ADS7124 register read/write demo that loops over registers, prints raw 24-bit conversions, and verifies continuous conversion mode.
- `adc/pyadi_example.py`: Uses the pyadi library to sample a single differential channel over SPI and print the voltage each second.

## adc Tools & Application Entry
- `adc/simple.py`: Full AD7124 register-initialization script that toggles GPIO22/27 and logs averaged on/off readings plus rolling statistics for quick characterization.
- `adc/simpler.py`: Slimmed-down variant of the above with reusable read_config/print helpers for manual experimentation.
- `application.py`: CLI entrypoint that instantiates `AssayInterface`, repeatedly runs ready/run/end loops, and signals kiosk screen changes on failure.
- `aq_curve/calculate.py`: Provides helpers to load optics logs, bucket data by dye/well, reject outliers, and fit a baseline line for fluorescence curves.
- `aq_curve/main.py`: Consumes optics logs, applies cross-talk correction, determines detection per well/dye, and writes the summarized JSON result file.
- `aq_lib/__init__.py`: Empty marker so the `aq_lib` hardware-control package can be imported elsewhere.

## aq_lib Core Drivers
- `aq_lib/config_module.py`: Loads `config_files/*.json`, exposes host-specific dictionaries, and provides helpers to locate serial devices by VID/PID or serial number.
- `aq_lib/hw_api.py`: `DockInterface` wrapper around simple_rpc/serial that timestamps runs, logs critical events, and exposes helpers like digitalWrite/read for the MCU.
- `aq_lib/lid_temperature.py`: Implements an ADS1115 I²C client supporting single-shot and continuous conversions plus comparator configuration for lid sensing.
- `aq_lib/mecrc16.py`: CRC-CCITT lookup table and helper functions used in Meerstetter frame integrity checks.
- `aq_lib/meerstetter.py`: Comprehensive Meerstetter TEC driver that discovers devices, wraps numerous parameter getters/setters, and handles framing/CRC on the serial link.
- `aq_lib/motor_class.py`: Defines the generic Motor plus Drawer and Axis subclasses with GPIO wiring, homing logic, and position tracking for the motion stages.

## aq_lib Control Helpers
- `aq_lib/regulate.py`: Starts the lid heater worker that continuously samples the ADS1115 and toggles GPIO21 (optionally via PWM) to maintain a voltage/temperature setpoint.
- `aq_lib/state_requests.py`: Provides REST helpers that talk to the kiosk FastAPI server to change screens, control timers, update result paths, and await button input.
- `aq_lib/tecControl.py`: Legacy example tying thermal profiles to Meerstetter commands and MCU fan pins via simple_rpc, illustrating how TEC runs were orchestrated.
- `aq_lib/thermal_engine.py`: Executes the action stream from `thermal_parser`, calling into the Meerstetter object, logging ramp/hold events, and invoking callbacks (fans/optics).
- `aq_lib/thermal_parser.py`: Generator that expands JSON profile steps into ramp/hold/enable/fan/optics commands with support for repeats and per-step ramp rates.
- `aq_lib/utils.py`: Miscellaneous helpers for JSON loading, timestamped logfile naming, dummy components, and centralized logging configurations.

## Web UI & Sensor Tools
- `aquila_web/hardware.py`: Simple helper that opens a simple_rpc Interface on `/dev/ttyACM0` so the FastAPI layer can forward hardware method calls.
- `aquila_web/main.py`: FastAPI app that drives the kiosk UI: serves static pages, manages run state/timers, handles profile selection, and publishes websocket updates.
- `aquila_web/stream/5_pressure_overlay_psi.py`: Streamlit dashboard for selecting docks/logs and overlaying PSI pressure traces with adjustable time windows.
- `aquila_web/stream/7_pcr_overlay.py`: Streamlit app for plotting TEC telemetry columns from multiple PCR runs with selectable Y-axes.
- `beam_breaks/test.py`: Continuously prints the GPIO states of the drawer/axis home sensors so you can debug beam-break switches.
- `dilutions.py`: Moves the axis/drawer, toggles the requested dye LED, and logs ADC readings per position to characterize dilution panels.

## Hardware Components
- `fan_class.py`: Thin class over GPIO17 that exposes `set_state` to turn the PCR fan on/off without repeating pin setup.
- `get_params.py`: Connects to the configured Meerstetter, iterates through every float/long register, and prints a comprehensive parameter dump.
- `led_class.py`: Reads LED pin mappings from Config and exposes on/off/set methods (with proper HIGH/LOW polarity) for FAM/ROX emitters.
- `led_current_verification.py`: Uses `OpticalRead` on dedicated sense channels to log LED current while alternately energizing the requested dye.
- `led_off.py`: Command-line helper that turns off whichever LED(s) you specify (default both) without running the full assay stack.
- `led_on.py`: Simple blinker that repeatedly toggles one or both LEDs every 0.8 seconds so you can visually confirm output.

## LED & Thermal Scripts
- `led/toggle.py`: Standalone loop that alternates GPIO22 and GPIO27 high/low with long delays to stress-test LED wiring.
- `led/turn_on_led.py`: One-shot script that drives GPIO22 high for five seconds, useful when probing the LED circuit.
- `lod_verification.py`: Positions the drawer/axis for a dye, blinks the LED, and records ADC voltages to verify the limit of detection workflow.
- `log_daq.py`: Reads the thermocouple serial stream (`/dev/ttyACM0`) and prints timestamped temperature lines for quick DAQ logging.
- `meer_ss_set_temp.py`: Enables the Meerstetter, sets a 60 °C target, and prints actual temperature every 0.5 seconds.
- `meer_ss.py`: Similar Meerstetter tuning script that steps through multiple target temperatures while also sampling an external thermocouple.

## Thermal & Motion Utilities
- `melt_curve.py`: Coordinates axis motion, optics captures, fan control, and thermal actions to execute a melt curve profile and log the data.
- `motor_disable.py`: Instantiates the Drawer motor class and immediately disables its enable pin; handy before servicing.
- `motor_test/test_motor.py`: Direct GPIO stepping sequence that jogs the drawer motor forwards/backwards and reports the home switch for wiring checks.
- `pcr_meer_off.py`: Safety routine that finds the Meerstetter, sets target temperature back to ambient, and disables the output stage.
- `PCR_plot.py`: Streamlit UI that loads an optics log and plots each well’s FAM/ROX curve using `aq_curve.get_curve`.
- `Raster.py`: Raster-scans the axis/drawer across a grid, capturing on/off LED readings to map excitation alignment.

## Run Control & ADC Tests (Set 1)
- `run_lid_heater_60.py`: Spawns the lid heater worker with a preset setpoint (0.304 by default) and prints a counter until interrupted.
- `run_lid_heater.py`: Similar runner that starts the lid heater thread with stop/quiet events so you can monitor behavior over time.
- `state_run_assay.py`: Main assay controller that manages axis/drawer motion, optics capture queue, thermal engine, lid heater, fan control, and kiosk state transitions.
- `test_adc.py`: Toggles LED 27 at fixed intervals, capturing AD7124 readings to compare illuminated vs. dark voltages.
- `test_adc2.py`: Selects the FAM channel, optionally moves to a requested axis position, and logs ADC output while blinking LED 27.
- `test_adc3.py`: Iterates through well positions (per dye), toggles LEDs, averages ADC values, and prints per-well statistics.

## Diagnostics (Set 2)
- `test_adc4.py`: Sweeps the axis X coordinate in fine steps, collecting long on/off averages to characterize spatial response uniformity.
- `test_axis.py`: CLI wrapper for homing, absolute moves, or repeated slip tests using the Axis motor class.
- `test_connection.py`: Serial test harness that waits for a dock RPC request, extracts its ID, and responds with firmware/protocol info.
- `test_curve.py`: Loads a stored optics log, runs `aq_curve.get_curve` for each well, and prints the resulting arrays for offline inspection.
- `test_drawer.py`: Command-line controls for homing, opening, or moving the drawer motor (including the configured “read” position).
- `test_exit.py`: Invokes `exit_kiosk.sh` to close the kiosk browser when testing remotely.

## Diagnostics (Set 3)
- `test_fan.py`: Sets the fan GPIO high or low (based on CLI arg) so you can quickly verify the fan wiring.
- `test_lm35.py`: Uses `OpticalRead` directly to sample the configured ADC channel (e.g., LM35 temperature sensor) and print the measured voltage.
- `test_positions.py`: Homes the axis, then moves to a requested position index using `Axis.goto_position` to confirm calibration.
- `test_state_request.py`: Standalone loop that calls the FastAPI endpoints via `state_requests`, exercising screen transitions, timer control, and drawer/run buttons.
- `toggle_pin.py`: Simple GPIO8 toggler that pulses the pin every 0.5 seconds for signal-probe or wiring tests.
