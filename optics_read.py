#!/usr/bin/python3
"""
Optics Read Diagnostic Tool

Takes optical readings using the ADC with proper LED sequencing.
Performs multiple readings to calculate average and standard deviation.

The reading process:
1. Set ADC channel for specified dye (FAM or ROX)
2. For each sample:
   - Take readings with LED ON (signal + ambient)
   - Take readings with LED OFF (ambient only)
   - Calculate difference (signal)
3. Report statistics

Commands:
    fam                 - Take FAM readings at current position
    rox                 - Take ROX readings at current position
    fam --samples N     - Take N samples (default: 5)
    fam --raw           - Show all raw readings, not just summary

Examples:
    python3 optics_read.py fam
    python3 optics_read.py rox --samples 10
    python3 optics_read.py fam --raw
"""

import sys
import time
import argparse
from datetime import datetime
from statistics import mean, stdev

# Try to import hardware libraries - graceful fallback for testing
try:
    from adc_class import OpticalRead
    from led_class import LED
    HARDWARE_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Hardware libraries not available: {e}", file=sys.stderr)
    print("[WARNING] Running in simulation mode", file=sys.stderr)
    HARDWARE_AVAILABLE = False


# ============================================================================
# CONFIGURATION - matches test_adc4_logged.py timing
# ============================================================================
DEFAULT_SAMPLES = 5          # Number of complete read cycles
READINGS_PER_STATE = 30      # Number of ADC readings per LED state
READINGS_TO_SKIP = 5         # Skip first N readings for stabilization (was k > 4)
READING_INTERVAL = 1.0/59.0  # Time between readings (seconds), synced to ~60Hz


def log(msg):
    """Print timestamped message to stderr for diagnostics"""
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[{timestamp}] {msg}", file=sys.stderr)


class MockADC:
    """Mock ADC for simulation mode"""
    class MockSPI:
        def xfer2(self, data):
            import random
            base = random.randint(0x10, 0x20)
            return [0x42, base, random.randint(0, 255), random.randint(0, 255)]
    
    def __init__(self):
        self.spi = self.MockSPI()
        
    def set_channel_dye(self, dye):
        log(f"[SIM] Set ADC channel for {dye}")
        
    def convert(self, reply):
        # Mock conversion - returns voltage in V
        raw = (reply[1] << 16) | (reply[2] << 8) | reply[3]
        return raw / 0xFFFFFF * 3.3  # Assuming 24-bit ADC, 3.3V ref


class MockLED:
    """Mock LED for simulation mode"""
    def __init__(self, dye):
        self.dye = dye
        self.state = False
        
    def on(self):
        self.state = True
        
    def off(self):
        self.state = False


def create_adc():
    """Create ADC instance"""
    if not HARDWARE_AVAILABLE:
        return MockADC()
    return OpticalRead()


def create_led(dye):
    """Create LED instance for specified dye"""
    if not HARDWARE_AVAILABLE:
        return MockLED(dye)
    return LED(dye)


def take_single_reading(adc, led, show_raw=False):
    """
    Take a single complete reading cycle (LED on and off).
    Matches the timing/sequence from test_adc4_logged.py
    
    Returns:
        tuple: (led_on_avg, led_off_avg, signal_diff) in mV
    """
    readings = {0: [], 1: []}  # 0=LED off, 1=LED on
    
    # Take readings for each LED state (ON first, then OFF - matches original)
    for led_state in [1, 0]:
        for k in range(READINGS_PER_STATE):
            time.sleep(READING_INTERVAL)
            
            if led_state:
                led.on()
            else:
                led.off()
            
            reply = adc.spi.xfer2([0x42] + [0x00, 0x00, 0x00])
            voltage_mv = 1000 * adc.convert(reply)
            
            # Skip first few readings for stabilization (k > 4 in original)
            if k >= READINGS_TO_SKIP:
                readings[led_state].append(voltage_mv)
    
    led.off()
    
    # Calculate averages
    led_on_avg = mean(readings[1]) if readings[1] else 0
    led_off_avg = mean(readings[0]) if readings[0] else 0
    signal = led_on_avg - led_off_avg
    
    if show_raw:
        log(f"  LED ON  ({len(readings[1])} readings): avg={led_on_avg:.4f} mV")
        log(f"  LED OFF ({len(readings[0])} readings): avg={led_off_avg:.4f} mV")
    
    return led_on_avg, led_off_avg, signal


def cmd_read(dye, num_samples=DEFAULT_SAMPLES, show_raw=False):
    """
    Take multiple optical readings and report statistics.
    
    Args:
        dye: 'fam' or 'rox'
        num_samples: Number of complete read cycles
        show_raw: If True, show individual readings
    """
    dye = dye.lower()
    if dye not in ['fam', 'rox']:
        log(f"ERROR: Dye must be 'fam' or 'rox', got '{dye}'")
        return -1
    
    log(f"COMMAND: Take {num_samples} {dye.upper()} readings")
    log("")
    log("Configuration:")
    log(f"  Dye: {dye.upper()}")
    log(f"  Samples: {num_samples}")
    log(f"  Readings per LED state: {READINGS_PER_STATE}")
    log(f"  Readings skipped (stabilization): {READINGS_TO_SKIP}")
    log(f"  Effective readings per state: {READINGS_PER_STATE - READINGS_TO_SKIP}")
    log(f"  Reading interval: {READING_INTERVAL*1000:.1f} ms (~60Hz sync)")
    log("")
    
    # Initialize hardware
    log("Initializing hardware...")
    adc = create_adc()
    time.sleep(0.1)
    adc.set_channel_dye(dye)
    led = create_led(dye)
    log("Hardware initialized.")
    log("")
    
    # Collect samples
    log("Taking readings...")
    log("-" * 50)
    
    led_on_values = []
    led_off_values = []
    signal_values = []
    
    t0 = time.time()
    
    for i in range(num_samples):
        log(f"Sample {i+1}/{num_samples}...")
        
        led_on, led_off, signal = take_single_reading(adc, led, show_raw)
        
        led_on_values.append(led_on)
        led_off_values.append(led_off)
        signal_values.append(signal)
        
        log(f"  Result: LED_ON={led_on:.4f} mV, LED_OFF={led_off:.4f} mV, Signal={signal:.4f} mV")
    
    elapsed = time.time() - t0
    led.off()
    
    log("-" * 50)
    log("")
    
    # Calculate statistics
    log("=" * 50)
    log("RESULTS SUMMARY")
    log("=" * 50)
    log("")
    
    # Individual readings table
    log("Individual Readings (mV):")
    log(f"  {'#':<4} {'LED ON':<12} {'LED OFF':<12} {'Signal':<12}")
    log(f"  {'-'*4} {'-'*12} {'-'*12} {'-'*12}")
    for i, (on, off, sig) in enumerate(zip(led_on_values, led_off_values, signal_values)):
        log(f"  {i+1:<4} {on:<12.4f} {off:<12.4f} {sig:<12.4f}")
    log("")
    
    # Statistics
    log("Statistics:")
    
    if len(signal_values) >= 2:
        signal_mean = mean(signal_values)
        signal_std = stdev(signal_values)
        signal_cv = (signal_std / abs(signal_mean) * 100) if signal_mean != 0 else 0
        
        led_on_mean = mean(led_on_values)
        led_on_std = stdev(led_on_values)
        
        led_off_mean = mean(led_off_values)
        led_off_std = stdev(led_off_values)
        
        log(f"  Signal (LED ON - OFF):")
        log(f"    Mean:   {signal_mean:.4f} mV")
        log(f"    StdDev: {signal_std:.4f} mV")
        log(f"    CV:     {signal_cv:.2f}%")
        log(f"    Min:    {min(signal_values):.4f} mV")
        log(f"    Max:    {max(signal_values):.4f} mV")
        log(f"    Range:  {max(signal_values) - min(signal_values):.4f} mV")
        log("")
        log(f"  LED ON:")
        log(f"    Mean:   {led_on_mean:.4f} mV")
        log(f"    StdDev: {led_on_std:.4f} mV")
        log("")
        log(f"  LED OFF (ambient):")
        log(f"    Mean:   {led_off_mean:.4f} mV")
        log(f"    StdDev: {led_off_std:.4f} mV")
    else:
        signal_mean = signal_values[0]
        log(f"  Signal: {signal_mean:.4f} mV (need 2+ samples for statistics)")
    
    log("")
    log(f"Total time: {elapsed:.1f}s ({elapsed/num_samples:.1f}s per sample)")
    log("")
    
    # Print summary line for easy parsing/logging
    std_str = f"±{stdev(signal_values):.4f}" if len(signal_values) >= 2 else "±N/A"
    print(f"# RESULT: {dye.upper()} Signal = {mean(signal_values):.4f} mV ({std_str} mV, n={num_samples})")
    
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Optics Read Diagnostic Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Reading Process (matches test_adc4_logged.py):
    1. Initialize ADC for specified dye channel
    2. For each sample:
       - Take {readings} readings with LED ON (skip first {skip})
       - Take {readings} readings with LED OFF (skip first {skip})
       - Calculate averages and difference (signal)
    3. Report mean, standard deviation, and coefficient of variation

Examples:
    %(prog)s fam               # 5 FAM readings
    %(prog)s rox               # 5 ROX readings  
    %(prog)s fam --samples 10  # 10 FAM readings
    %(prog)s rox --raw         # Show detailed per-sample info
        """.format(readings=READINGS_PER_STATE, skip=READINGS_TO_SKIP)
    )
    
    parser.add_argument('dye', type=str, choices=['fam', 'rox', 'FAM', 'ROX'],
                        help='Dye to read (fam or rox)')
    parser.add_argument('--samples', '-n', type=int, default=DEFAULT_SAMPLES,
                        help=f'Number of complete read cycles (default: {DEFAULT_SAMPLES})')
    parser.add_argument('--raw', '-r', action='store_true',
                        help='Show detailed readings for each sample')
    
    args = parser.parse_args()
    
    # Print header
    log("=" * 60)
    log("OPTICS READ DIAGNOSTIC TOOL")
    log("=" * 60)
    log(f"Hardware available: {HARDWARE_AVAILABLE}")
    log(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("")
    
    try:
        ret = cmd_read(args.dye, args.samples, args.raw)
    except KeyboardInterrupt:
        log("\nAborted by user")
        ret = 1
    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        ret = -1
    
    log("=" * 60)
    log("COMPLETE")
    log("=" * 60)
    
    return ret


if __name__ == "__main__":
    sys.exit(main() or 0)
