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
log(f"RASTER SCAN (X-AXIS REVERSE) - {dye.upper()}")
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

# Y range (normal direction - home to far)
dr0 = 0                              # Start at home (Y=0)
dr1 = drawer.read_steps + 500        # End at read_steps + 500

log(f"")
log(f"Scan parameters:")
log(f"  Dye: {dye}, Offset: {offset}")
log(f"  Axis X range: {ax_max} to {ax_min} (REVERSE - far to home)")
log(f"  Drawer Y range: {dr0} to {dr1} (normal - home to far)")
log(f"  Drawer read_steps (from config): {drawer.read_steps}")
log(f"  Axis positions: {axis.positions}")
log(f"")
log(f"NOTE: X scans from FAR towards HOME, Y scans normally")
log(f"")
log(f"Starting raster scan...")
log(f"")

row_count = 0
# Scan Y from home to far (normal direction)
for y in range(dr0, dr1, 40):
    row_count += 1
    drawer.move_abs_wo_home_flag(y)
    drawer.disable()
    
    # Move to far end of X before scanning this row
    axis.move_abs_wo_home_flag(ax_max)
    
    col_count = 0
    # Scan X from far to home (REVERSE direction)
    for x in range(ax_max, ax_min - 1, -40):
        col_count += 1
        axis.move_abs_wo_home_flag(x)
        axis.disable()

        s_on = 0
        N_on = 1
        s_off = 0
        N_off = 1

        led.on()
        time.sleep(0.1)
        for i in range(20):
            reply = adc.spi.xfer2([0x42] + [0x00, 0x00, 0x00])
            voltage = 1000 * adc.convert(reply)
            time.sleep(1/60.0)
            s_on += voltage

        led.off()
        time.sleep(0.1)
        for i in range(20):
            reply = adc.spi.xfer2([0x42] + [0x00, 0x00, 0x00])
            voltage = 1000 * adc.convert(reply)
            time.sleep(1/60.0)
            s_off += voltage

        print(x, y, s_on/20 - s_off/20)
    
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
log(f"Final axis position: {axis.position}")
log(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
