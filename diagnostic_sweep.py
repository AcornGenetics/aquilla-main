#!/usr/bin/python3
"""
Full Diagnostic Sweep Tool

Performs systematic diagnostic tests combining motor positioning and optics reads.
Useful for identifying position-related read inconsistencies.

Commands:
    drawer-sweep              - Test readings at multiple drawer positions
    axis-sweep                - Test readings at all well positions  
    repeatability N           - Take N readings at same position to test consistency

Examples:
    python3 diagnostic_sweep.py axis-sweep --dye fam
    python3 diagnostic_sweep.py drawer-sweep --dye rox --start 140 --end 180 --step 5
    python3 diagnostic_sweep.py repeatability 20 --dye fam --well 3
"""

import sys
import time
import argparse
from datetime import datetime
from statistics import mean, stdev

# Try to import hardware libraries
try:
    import RPi.GPIO as GPIO
    from aq_lib.motor_class import Axis, Drawer
    from aq_lib.config_module import Config
    from adc_class import OpticalRead
    from led_class import LED
    HARDWARE_AVAILABLE = True
    
    # Load config
    config = Config()
    
    # Drawer limits
    DRAWER_MAX_STEPS = config.drawer["open_steps"]      # 4500
    DRAWER_READ_STEPS = config.drawer["read_steps"]     # 151 or 160
    
    # Axis limits  
    AXIS_WELL_ONE = config.axis["well_one"]             # 300
    AXIS_WELL_SPACING = config.axis["well_spacing"]     # 359
    AXIS_POSITIONS = [AXIS_WELL_ONE + AXIS_WELL_SPACING * i for i in range(6)]
    AXIS_MAX_STEPS = AXIS_POSITIONS[5] + 100            # ~2195
    
except ImportError as e:
    print(f"[WARNING] Hardware libraries not available: {e}", file=sys.stderr)
    print("[WARNING] Running in simulation mode", file=sys.stderr)
    HARDWARE_AVAILABLE = False
    
    # Defaults for simulation
    DRAWER_MAX_STEPS = 4500
    DRAWER_READ_STEPS = 151
    AXIS_WELL_ONE = 300
    AXIS_WELL_SPACING = 359
    AXIS_POSITIONS = [AXIS_WELL_ONE + AXIS_WELL_SPACING * i for i in range(6)]
    AXIS_MAX_STEPS = AXIS_POSITIONS[5] + 100


# ============================================================================
# CONFIGURATION - matches test_adc4_logged.py
# ============================================================================
READINGS_PER_SAMPLE = 30
READINGS_TO_SKIP = 5
READING_INTERVAL = 1.0/59.0
DEFAULT_SAMPLES_PER_POSITION = 3

# Dye to position mapping
DYE_WELL_MAP = {
    'rox': {1: 0, 2: 1, 3: 2, 4: 3},
    'fam': {1: 2, 2: 3, 3: 4, 4: 5},
}


def log(msg):
    """Print timestamped message to stderr for diagnostics"""
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[{timestamp}] {msg}", file=sys.stderr)


def take_reading(adc, led):
    """Take a single complete reading cycle, returns signal in mV"""
    readings = {0: [], 1: []}
    
    for led_state in [1, 0]:
        for k in range(READINGS_PER_SAMPLE):
            time.sleep(READING_INTERVAL)
            if led_state:
                led.on()
            else:
                led.off()
            reply = adc.spi.xfer2([0x42, 0x00, 0x00, 0x00])
            voltage_mv = 1000 * adc.convert(reply)
            if k >= READINGS_TO_SKIP:
                readings[led_state].append(voltage_mv)
    
    led.off()
    
    led_on_avg = mean(readings[1]) if readings[1] else 0
    led_off_avg = mean(readings[0]) if readings[0] else 0
    return led_on_avg - led_off_avg


def cmd_drawer_sweep(dye, start, end, step, samples_per_pos, axis_pos=None):
    """Sweep drawer through positions and take readings at each"""
    log(f"DRAWER SWEEP: {dye.upper()}")
    log(f"  Range: {start} to {end} steps, increment {step}")
    log(f"  Samples per position: {samples_per_pos}")
    log("")
    
    if not HARDWARE_AVAILABLE:
        log("ERROR: Cannot run sweep in simulation mode")
        return -1
    
    # Validate range
    if start < 0 or end > DRAWER_MAX_STEPS:
        log(f"ERROR: Drawer range must be 0-{DRAWER_MAX_STEPS}")
        return -1
    
    # Initialize
    drawer = Drawer()
    axis = Axis()
    adc = OpticalRead()
    time.sleep(0.1)
    adc.set_channel_dye(dye)
    led = LED(dye)
    
    # Home everything
    log("Homing drawer...")
    drawer.home()
    log("Homing axis...")
    axis.home()
    
    # Move axis to specified or default position
    if axis_pos is None:
        # Default: use position 2 (overlap position for both dyes)
        axis_pos = 2
    target_steps = AXIS_POSITIONS[axis_pos]
    log(f"Moving axis to position {axis_pos} ({target_steps} steps)...")
    axis.move_abs_wo_home_flag(target_steps, 0.001)
    
    results = []
    
    log("")
    log("Starting sweep...")
    log("-" * 70)
    log(f"{'Drawer Pos':<12} {'Signal (mV)':<15} {'StdDev':<12} {'Readings'}")
    log("-" * 70)
    
    try:
        for pos in range(start, end + 1, step):
            # Move drawer to position (home first for consistency)
            drawer.home()
            drawer.move_wo_home_flag(pos, 0.001)
            time.sleep(0.2)  # Settle time
            
            # Take readings
            readings = []
            for _ in range(samples_per_pos):
                signal = take_reading(adc, led)
                readings.append(signal)
            
            avg = mean(readings)
            std = stdev(readings) if len(readings) >= 2 else 0
            
            results.append({
                'position': pos,
                'signal_mean': avg,
                'signal_std': std,
                'readings': readings
            })
            
            readings_str = ', '.join([f'{r:.2f}' for r in readings])
            log(f"{pos:<12} {avg:<15.4f} {std:<12.4f} [{readings_str}]")
            
    finally:
        led.off()
        drawer.disable()
        axis.disable()
    
    log("-" * 70)
    log("")
    
    # Summary
    if results:
        all_signals = [r['signal_mean'] for r in results]
        best_idx = all_signals.index(max(all_signals))
        log("SUMMARY:")
        log(f"  Best position: {results[best_idx]['position']} steps (signal: {max(all_signals):.4f} mV)")
        log(f"  Signal range: {min(all_signals):.4f} to {max(all_signals):.4f} mV")
        log(f"  Total variation: {max(all_signals) - min(all_signals):.4f} mV")
        log("")
        log(f"  Current read_steps in config: {DRAWER_READ_STEPS}")
        if results[best_idx]['position'] != DRAWER_READ_STEPS:
            log(f"  NOTE: Best position differs from config by {results[best_idx]['position'] - DRAWER_READ_STEPS} steps")
    
    return 0


def cmd_axis_sweep(dye, samples_per_pos):
    """Test readings at all well positions for specified dye"""
    log(f"AXIS SWEEP: {dye.upper()}")
    log(f"  Samples per position: {samples_per_pos}")
    log("")
    
    if not HARDWARE_AVAILABLE:
        log("ERROR: Cannot run sweep in simulation mode")
        return -1
    
    # Initialize
    drawer = Drawer()
    axis = Axis()
    adc = OpticalRead()
    time.sleep(0.1)
    adc.set_channel_dye(dye)
    led = LED(dye)
    
    # Home and move drawer to read position
    log("Homing drawer...")
    drawer.home()
    log(f"Moving drawer to read position ({DRAWER_READ_STEPS} steps)...")
    drawer.move_wo_home_flag(DRAWER_READ_STEPS, 0.001)
    log("Homing axis...")
    axis.home()
    
    # Determine which positions to test based on dye
    if dye.lower() == 'rox':
        positions = [0, 1, 2, 3]
        well_labels = ['Well 1', 'Well 2', 'Well 3', 'Well 4']
    else:  # fam
        positions = [2, 3, 4, 5]
        well_labels = ['Well 1', 'Well 2', 'Well 3', 'Well 4']
    
    results = []
    
    log("")
    log("Starting axis sweep...")
    log("-" * 75)
    log(f"{'Pos Idx':<10} {'Well':<10} {'Steps':<10} {'Signal (mV)':<15} {'StdDev':<12}")
    log("-" * 75)
    
    try:
        for i, pos_idx in enumerate(positions):
            steps = AXIS_POSITIONS[pos_idx]
            
            # Move axis (home first for consistency)
            axis.home()
            axis.move_abs_wo_home_flag(steps, 0.001)
            time.sleep(0.2)  # Settle time
            
            # Take readings
            readings = []
            for _ in range(samples_per_pos):
                signal = take_reading(adc, led)
                readings.append(signal)
            
            avg = mean(readings)
            std = stdev(readings) if len(readings) >= 2 else 0
            
            results.append({
                'position': pos_idx,
                'well': well_labels[i],
                'steps': steps,
                'signal_mean': avg,
                'signal_std': std,
                'readings': readings
            })
            
            log(f"{pos_idx:<10} {well_labels[i]:<10} {steps:<10} {avg:<15.4f} {std:<12.4f}")
            
    finally:
        led.off()
        drawer.disable()
        axis.disable()
    
    log("-" * 75)
    log("")
    
    # Summary
    log("SUMMARY:")
    for r in results:
        cv = (r['signal_std'] / abs(r['signal_mean']) * 100) if r['signal_mean'] != 0 else 0
        log(f"  {r['well']}: {r['signal_mean']:.4f} mV (CV: {cv:.2f}%)")
    
    return 0


def cmd_repeatability(dye, num_readings, well=None, drawer_pos=None):
    """Take multiple readings at same position to test consistency"""
    log(f"REPEATABILITY TEST: {dye.upper()}")
    log(f"  Number of readings: {num_readings}")
    if well is not None:
        log(f"  Well: {well}")
    if drawer_pos is not None:
        log(f"  Drawer position: {drawer_pos} steps")
    else:
        log(f"  Drawer position: {DRAWER_READ_STEPS} steps (from config)")
    log("")
    
    if not HARDWARE_AVAILABLE:
        log("ERROR: Cannot run test in simulation mode")
        return -1
    
    # Initialize
    drawer = Drawer()
    axis = Axis()
    adc = OpticalRead()
    time.sleep(0.1)
    adc.set_channel_dye(dye)
    led = LED(dye)
    
    # Position motors
    log("Positioning motors...")
    drawer.home()
    if drawer_pos is not None:
        drawer.move_wo_home_flag(drawer_pos, 0.001)
    else:
        drawer.move_wo_home_flag(DRAWER_READ_STEPS, 0.001)
    
    axis.home()
    if well is not None:
        # Map well to position based on dye
        pos_idx = DYE_WELL_MAP[dye.lower()][well]
        axis.move_abs_wo_home_flag(AXIS_POSITIONS[pos_idx], 0.001)
        log(f"Axis at position {pos_idx} ({AXIS_POSITIONS[pos_idx]} steps) for {dye.upper()} well {well}")
    else:
        # Default to position 2
        axis.move_abs_wo_home_flag(AXIS_POSITIONS[2], 0.001)
        log(f"Axis at position 2 ({AXIS_POSITIONS[2]} steps)")
    
    time.sleep(0.5)  # Settle time
    
    log("")
    log("Taking readings (motors stationary)...")
    log("-" * 50)
    
    readings = []
    try:
        for i in range(num_readings):
            signal = take_reading(adc, led)
            readings.append(signal)
            log(f"  Reading {i+1:3d}: {signal:.4f} mV")
    finally:
        led.off()
        drawer.disable()
        axis.disable()
    
    log("-" * 50)
    log("")
    
    # Statistics
    avg = mean(readings)
    std = stdev(readings) if len(readings) >= 2 else 0
    cv = (std / abs(avg) * 100) if avg != 0 else 0
    
    log("RESULTS:")
    log(f"  Mean:     {avg:.4f} mV")
    log(f"  StdDev:   {std:.4f} mV")
    log(f"  CV:       {cv:.2f}%")
    log(f"  Min:      {min(readings):.4f} mV")
    log(f"  Max:      {max(readings):.4f} mV")
    log(f"  Range:    {max(readings) - min(readings):.4f} mV")
    log("")
    
    # Assessment
    if cv < 1.0:
        log("ASSESSMENT: Excellent repeatability (CV < 1%)")
    elif cv < 3.0:
        log("ASSESSMENT: Good repeatability (CV < 3%)")
    elif cv < 5.0:
        log("ASSESSMENT: Acceptable repeatability (CV < 5%)")
    else:
        log("ASSESSMENT: Poor repeatability (CV >= 5%)")
        log("            -> Investigate mechanical positioning consistency")
    
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Full Diagnostic Sweep Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Hardware Limits (from config):
    Drawer: 0 to {drawer_max} steps (read position: {drawer_read})
    Axis positions: {axis_positions}

Examples:
    %(prog)s drawer-sweep --dye fam --start 140 --end 180 --step 5
    %(prog)s axis-sweep --dye rox --samples 5
    %(prog)s repeatability 20 --dye fam --well 3
    %(prog)s repeatability 10 --dye rox --drawer-pos 155
        """.format(
            drawer_max=DRAWER_MAX_STEPS,
            drawer_read=DRAWER_READ_STEPS,
            axis_positions=AXIS_POSITIONS
        )
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Diagnostic test to run')
    
    # Drawer sweep
    drawer_parser = subparsers.add_parser('drawer-sweep', 
        help='Sweep drawer positions and measure signal')
    drawer_parser.add_argument('--dye', type=str, required=True, choices=['fam', 'rox'])
    drawer_parser.add_argument('--start', type=int, default=DRAWER_READ_STEPS - 20, 
                               help=f'Start position (default: {DRAWER_READ_STEPS - 20})')
    drawer_parser.add_argument('--end', type=int, default=DRAWER_READ_STEPS + 20,
                               help=f'End position (default: {DRAWER_READ_STEPS + 20})')
    drawer_parser.add_argument('--step', type=int, default=5, help='Step size (default: 5)')
    drawer_parser.add_argument('--samples', type=int, default=3, help='Samples per position')
    drawer_parser.add_argument('--axis-pos', type=int, choices=[0,1,2,3,4,5], 
                               help='Axis position index (default: 2)')
    
    # Axis sweep
    axis_parser = subparsers.add_parser('axis-sweep',
        help='Test all well positions for a dye')
    axis_parser.add_argument('--dye', type=str, required=True, choices=['fam', 'rox'])
    axis_parser.add_argument('--samples', type=int, default=3, help='Samples per position')
    
    # Repeatability test
    repeat_parser = subparsers.add_parser('repeatability',
        help='Test reading repeatability at single position')
    repeat_parser.add_argument('num_readings', type=int, help='Number of readings')
    repeat_parser.add_argument('--dye', type=str, required=True, choices=['fam', 'rox'])
    repeat_parser.add_argument('--well', type=int, choices=[1, 2, 3, 4], help='Well number (1-4)')
    repeat_parser.add_argument('--drawer-pos', type=int, help='Drawer position in steps')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    log("=" * 60)
    log("DIAGNOSTIC SWEEP TOOL")
    log("=" * 60)
    log(f"Hardware available: {HARDWARE_AVAILABLE}")
    log(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("")
    
    try:
        if args.command == 'drawer-sweep':
            ret = cmd_drawer_sweep(args.dye, args.start, args.end, args.step, 
                                   args.samples, args.axis_pos)
        elif args.command == 'axis-sweep':
            ret = cmd_axis_sweep(args.dye, args.samples)
        elif args.command == 'repeatability':
            ret = cmd_repeatability(args.dye, args.num_readings, args.well, args.drawer_pos)
        else:
            parser.print_help()
            ret = 1
    except KeyboardInterrupt:
        log("\nAborted by user")
        ret = 1
    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        ret = -1
    
    log("")
    log("=" * 60)
    log(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 60)
    
    return ret


if __name__ == "__main__":
    sys.exit(main() or 0)
