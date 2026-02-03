"""
Minimal stepper client for Arduino-controlled X/Y/Z steppers.
Structure preserved from earlier version: move_x, move_y, move_z, raster_scan_x_then_z.

CHANGE: Host now *waits for "Done"* from Arduino before applying dwell,
so a dwell like 5000 ms happens AFTER each X pass completes.

Requires: pip install pyserial
"""

import time
import serial
from math import ceil

# ----------------------------
# Serial setup (adjust port!)
# ----------------------------
ARDUINO_PORT = "/dev/ttyACM0"   # e.g. "COM3" on Windows, "/dev/ttyACM0" or "/dev/ttyUSB0" on Linux/Mac
BAUD = 9600
# Overall time to wait for "Done" from Arduino per command (seconds)
WAIT_TIMEOUT_S = 300

arduino = serial.Serial(port=ARDUINO_PORT, baudrate=BAUD, timeout=0.5)
time.sleep(2)  # give Arduino time to reset

# ----------------------------
# Low-level helpers
# ----------------------------
def _send_and_wait_done(cmd: str, wait_timeout_s: float = WAIT_TIMEOUT_S) -> str:
    """
    Send a line to the Arduino and block until it replies with 'Done' (case-insensitive)
    or an error line starting with 'ERR'. Returns the last line seen.
    """
    arduino.reset_input_buffer()
    arduino.write((cmd.strip() + "\n").encode())

    t0 = time.time()
    last = ""
    while True:
        line = arduino.readline().decode(errors="ignore").strip()
        if line:
            last = line
            if "done" in line.lower():
                return line
            if line.startswith("ERR"):
                return line
        if time.time() - t0 > wait_timeout_s:
            raise TimeoutError(f"Timeout waiting for 'Done' after '{cmd}'. Last line: '{last}'")

def move_x(direction: str, steps: int):
    """direction: '+' or '-', steps: int >= 0"""
    resp = _send_and_wait_done(f"X{direction}{int(steps)}")
    if resp: print(f"[X] {resp}")

def move_y(direction: str, steps: int):
    resp = _send_and_wait_done(f"Y{direction}{int(steps)}")
    if resp: print(f"[Y] {resp}")

def move_z(direction: str, steps: int):
    resp = _send_and_wait_done(f"Z{direction}{int(steps)}")
    if resp: print(f"[Z] {resp}")

# ----------------------------
# Raster scan routine
# ----------------------------
def raster_scan_x_then_z(
    x_span_steps: int,
    z_step_per_layer: int,
    total_z_steps: int,
    start_dir_x: str = "+",
    dwell_ms_each_pass: int = 0
):
    """
    Perform a raster scan:
      1) Move X across x_span_steps (start_dir_x),
      2) Raise Z by z_step_per_layer,
      3) Move X back x_span_steps (opposite direction),
      4) Repeat until total_z_steps reached/exceeded.

    Args:
        x_span_steps: number of X steps for each pass (forward/back).
        z_step_per_layer: Z steps to move UP after each X pass.
        total_z_steps: total Z height to accumulate from the starting Z.
        start_dir_x: '+' or '-' for the first X pass direction.
        dwell_ms_each_pass: pause AFTER each X pass completes (milliseconds).
    """
    assert start_dir_x in ("+", "-"), "start_dir_x must be '+' or '-'"
    assert x_span_steps >= 0 and z_step_per_layer > 0 and total_z_steps > 0

    layers = ceil(total_z_steps / z_step_per_layer)
    dir_x = start_dir_x

    print(f"Starting raster: {layers} layers "
          f"(@ Z {z_step_per_layer} steps/layer) to reach ≥ {total_z_steps} Z steps")

    for layer in range(layers):
        # X pass
        print(f"Layer {layer+1}/{layers}: X{dir_x}{x_span_steps}")
        move_x(dir_x, x_span_steps)
        if dwell_ms_each_pass > 0:
            print(f"Dwell {dwell_ms_each_pass} ms")
            time.sleep(dwell_ms_each_pass / 1000.0)

        # Raise Z
        print(f"Layer {layer+1}/{layers}: Z+{z_step_per_layer}")
        move_z("+", z_step_per_layer)
        time.sleep(1)

        # X return pass (flip direction)
        dir_x = "-" if dir_x == "+" else "+"
        print(f"Layer {layer+1}/{layers}: X{dir_x}{x_span_steps}")
        move_x(dir_x, x_span_steps)
        if dwell_ms_each_pass > 0:
            print(f"Dwell {dwell_ms_each_pass} ms")
            time.sleep(dwell_ms_each_pass / 1000.0)
    
    #return to starting z position
    time.sleep(1)
    move_z('-', total_z_steps)

    print("Raster complete.")

if __name__ == "__main__":
   
    # Basic moves (unchanged)
     #move_x('-', 8600)
     #time.sleep(2)
     #move_x('+', 8600)

     #move_y('-', 200)
     #move_z('-', 50)

    # Example raster:
    #   Scan X 4000 steps forward, raise Z by 100 steps, scan back,
    #   repeat until total Z rise = 1200 steps (=> 12 layers).
   

   raster_scan_x_then_z(
        x_span_steps = 8600,
        z_step_per_layer = 50,
        total_z_steps = 50,
        start_dir_x = "-",
        dwell_ms_each_pass= 2000  # set e.g. 200 for a 200 ms pause each pass
    )








