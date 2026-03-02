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

led = LED( dye )

adc = OpticalRead()
adc.set_channel_dye( dye )

t0 = time.time()

drawer.home()
axis.home()

if dye == "fam": offset = 2
elif dye == "rox": offset = 0

ax_min = axis.positions[offset ]- 100
ax_max = axis.positions[offset + 3]+100

dr0 = drawer.read_steps - 500
dr1 = drawer.read_steps + 500

for y in range ( dr0, dr1, 40 ):
    drawer.move_abs_wo_home_flag ( y )
    drawer.disable()
    for x in range ( ax_min, ax_max, 40 ):
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



led.off()
