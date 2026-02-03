import time 
from adc_class import OpticalRead
from statistics import stdev
import time
import sys
import sys
from led_class import LED
from motor_class import Axis, Drawer
import logging
import logging.config

from aq_lib.utils import load_json
from aq_lib.utils import LogFileName
from aq_lib.utils import LOGGING_CONFIG

logging.config.dictConfig( LOGGING_CONFIG )
logger = logging.getLogger( "aquila.optics" )

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

axis = Axis()
drawer = Drawer()
axis.home()
drawer.home()
drawer.read()

led = LED( dye )

adc = OpticalRead()
time.sleep ( 0.1 )
adc.set_channel_dye( dye )

for i in range ( 0 ):
    time.sleep ( 0.1 )
    reply2 = adc.spi.xfer2( [ 0x42 ] + [0x00,0x00, 0x00] )

fp = open ( logfile, "w" )
#fp = sys.stdout
t0 = time.time()
for position in range(0,4) if dye == "rox" else range(2,6):
    axis.goto_position( position )
    time.sleep ( 0.1 )
    for i in range ( 1 ):
        s = [0,0]
        N = [0,0]
        avg = [0,0]
        for led_state in [1,0]:
            for k in range ( 10 ):
                time.sleep ( 1.0/59.0 )
                if led_state: 
                    led.on()
                else:
                    led.off()

                dt = time.time() - t0
                reply2 = adc.spi.xfer2( [ 0x42 ] + [0x00,0x00, 0x00] )
                voltage1 = 1000*adc.convert ( reply2 )
                if k>3:
                    s[led_state] += voltage1
                    N[led_state] += 1
                    avg[led_state] = s[led_state] / N[led_state]

        print ( 
            "%.6f "%dt,
            dye, 
            " %d "%position, 
            *["%02x"%r for r in reply2],
            " %.5f "%voltage1,
            led_state,
            "%.6f "%avg[1], 
            "%.6f "%avg[0],  
            "%.6f "%(avg[1]-avg[0]),
            file = fp
        )
        led.off()

led.off()
drawer.open()
