import time 
from adc_class import OpticalRead
from statistics import stdev
import time
import sys
from aq_lib.config_module import Config
import sys
from led_class import LED
from aq_lib.motor_class import Drawer
from aq_lib.motor_class import Axis
from datetime import datetime


def log(msg):
    """Print to stderr for motor diagnostics"""
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[{timestamp}] {msg}", file=sys.stderr)


drawer = Drawer()
axis = Axis()

config = Config()

try:
    dye = sys.argv[1].lower()
    print ( "#", dye )
    assert dye in [ "fam", "rox" ]
except Exception as e:
    print ( e )
    print ( "Usage:", sys.argv[0], "fam/rox" )
    exit ( 0 )

log(f"=" * 60)
log(f"RASTER SCAN - {dye.upper()}")
log(f"=" * 60)
log(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

led = LED( dye )

adc = OpticalRead()
adc.set_channel_dye( dye )

t0 = time.time()

log("Homing drawer...")
drawer.home()
log(f"Drawer homed. Position: {drawer.position}")

log("Homing axis...")
axis.home()
log(f"Axis homed. Position: {axis.position}")

if dye == "fam": offset = 2
elif dye == "rox": offset = 0

ax_min = axis.positions[offset] - 100
ax_max = axis.positions[offset + 3] + 100

# FIXED: Y coordinates now match host_config coordinate system
# Y=0 is home position, Y=read_steps (160) is the read position
# Scan from 0 (home) to read_steps + margin
# This ensures Y values in data match physical positions from home

dr0 = 0                              # Start at home (Y=0 = physical home)
dr1 = drawer.read_steps + 500        # End at read_steps + 500

log(f"")
log(f"Scan parameters:")
log(f"  Dye: {dye}, Offset: {offset}")
log(f"  Axis X range: {ax_min} to {ax_max}")
log(f"  Drawer Y range: {dr0} to {dr1}")
log(f"  Drawer read_steps (from config): {drawer.read_steps}")
log(f"  Axis positions: {axis.positions}")
log(f"")
log(f"NOTE: Y=0 is home, Y={drawer.read_steps} is the read position")
log(f"")
log(f"Starting raster scan...")
log(f"")

row_count = 0
for y in range ( dr0, dr1, 40 ):
    row_count += 1
    drawer.move_abs_wo_home_flag ( y )
    drawer.disable()
    
    col_count = 0
    for x in range ( ax_min, ax_max, 40 ):
        col_count += 1
        axis.move_abs_wo_home_flag ( x )
        axis.disable()

        s_on = 0
        N_on = 1
        s_off = 0
        N_off = 1

        led.on()
        time.sleep ( 0.1 )
        for i in range ( 20 ):
            reply = adc.spi.xfer2( [ 0x42 ] + [0x00,0x00, 0x00] )
            voltage = 1000*adc.convert ( reply )
            time.sleep ( 1/60.0 )
            s_on += voltage
            #print ( reply, voltage )

        led.off()
        time.sleep ( 0.1 )
        for i in range ( 20 ):
            reply = adc.spi.xfer2( [ 0x42 ] + [0x00,0x00, 0x00] )
            voltage = 1000*adc.convert ( reply )
            time.sleep ( 1/60.0 )
            s_off += voltage
            #print ( reply, voltage )
        print( x, y, s_on/20 - s_off/20 )
    
    # Log row completion
    log(f"Row {row_count}: Y={y}, {col_count} X points, axis_pos={axis.position}, drawer_pos={drawer.position}")

led.off()

scan_time = time.time() - t0
log(f"")
log(f"=" * 60)
log(f"SCAN COMPLETE")
log(f"=" * 60)
log(f"Total time: {scan_time:.1f}s ({scan_time/60:.1f} min)")
log(f"Total rows: {row_count}")
log(f"Final drawer position: {drawer.position}")
log(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
