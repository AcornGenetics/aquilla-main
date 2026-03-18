import time 
from adc_class import OpticalRead
from statistics import stdev
import time
import sys
import sys
from led_class import LED
from aq_lib.motor_class import Axis, Drawer
import logging
import logging.config
from datetime import datetime

from aq_lib.utils import load_json
from aq_lib.utils import LogFileName
from aq_lib.utils import LOGGING_CONFIG

logging.config.dictConfig( LOGGING_CONFIG )
logger = logging.getLogger( "aquila.optics" )


def log(msg):
    """Print to stderr for motor diagnostics"""
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[{timestamp}] {msg}", file=sys.stderr)


try:
    dye = sys.argv[1].lower()
    print ( "#", dye )
    assert dye.lower() in [ "fam", "rox" ]
except Exception as e:
    print ( e )
    print ( "Usage:", sys.argv[0], "fam/rox" )
    exit ( 0 )

lfn = LogFileName()
logfile = lfn.get_optics_log_filename()
logger.info("ADC scan staring")
logger.info("Log filename: %s", logfile)

log(f"=" * 60)
log(f"ADC SCAN (REVERSE DIRECTION) - {dye.upper()}")
log(f"=" * 60)
log(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

axis = Axis()
#drawer = Drawer()

log("Homing axis...")
axis.home()
log(f"Axis homed. Position: {axis.position}")
#drawer.home()
#drawer.read()

led = LED( dye )

adc = OpticalRead()
time.sleep ( 0.1 )
adc.set_channel_dye( dye )

# Calculate scan range - start from far end, move towards home
scan_start = axis.positions[5] + 100  # Furthest point (e.g., 2175)
scan_end = 0                           # Home end
scan_step = 20

log(f"")
log(f"Scan parameters:")
log(f"  Dye: {dye}")
log(f"  Axis X range: {scan_start} to {scan_end} (step -{scan_step})")
log(f"  Direction: FAR -> HOME (reverse)")
log(f"  Axis positions: {axis.positions}")
log(f"")

# Move to starting position (far end) first
log(f"Moving to start position: {scan_start}")
axis.move_abs_wo_home_flag(scan_start)
log(f"At start position. axis_pos={axis.position}")
log(f"")
log(f"Starting ADC scan (reverse direction)...")
log(f"")

for i in range ( 0 ):
    time.sleep ( 0.1 )
    reply2 = adc.spi.xfer2( [ 0x42 ] + [0x00,0x00, 0x00] )

fp0 = open ( logfile, "w" )
fp1 = sys.stdout
t0 = time.time()
scan_count = 0

# Scan from far end towards home (reverse direction)
for x in range(scan_start, scan_end - 1, -scan_step):
    scan_count += 1
    axis.move_abs_wo_home_flag( x )
    time.sleep ( 0.1 )
    for i in range ( 1 ):
        s = [0,0]
        N = [0,0]
        avg = [0,0]
        for led_state in [1,0]:
            for k in range ( 30 ):
                time.sleep ( 1.0/59.0 )
                if led_state: 
                    led.on()
                else:
                    led.off()

                dt = time.time() - t0
                reply2 = adc.spi.xfer2( [ 0x42 ] + [0x00,0x00, 0x00] )
                voltage1 = 1000*adc.convert ( reply2 )
                if k > 4:
                    s[led_state] += voltage1
                    N[led_state] += 1
                    avg[led_state] = s[led_state] / N[led_state]

        print_args =  ( 
            "%.6f "%dt,
            x, 
            dye, 
            *["%02x"%r for r in reply2],
            " %.5f "%voltage1,
            led_state,
            "%.6f "%avg[1], 
            "%.6f "%avg[0],  
            "%.6f "%(avg[1]-avg[0]),
        )
        print ( *print_args, file = fp0 )
        print ( *print_args, file = fp1 )
        led.off()
    
    # Log position after each X move
    log(f"Position {scan_count}: X={x}, axis_pos={axis.position}")

led.off()

scan_time = time.time() - t0
log(f"")
log(f"=" * 60)
log(f"SCAN COMPLETE")
log(f"=" * 60)
log(f"Total time: {scan_time:.1f}s ({scan_time/60:.1f} min)")
log(f"Total positions: {scan_count}")
log(f"Final axis position: {axis.position}")
log(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

#drawer.open()
