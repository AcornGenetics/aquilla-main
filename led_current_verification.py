import sys
from adc_class import OpticalRead
from led_class import LED
import time

dye = sys.argv[1].lower()

led = LED( dye )
adc = OpticalRead()  # Measuring LED current. 
time.sleep ( 0.1 )

led_sense = { "fam":(14,13,), "rox": ( 8,10,) }

adc.set_channel( *led_sense[dye] )

for i in range ( 0 ):
    time.sleep ( 0.1 )
    reply2 = adc.spi.xfer2( [ 0x42 ] + [0x00,0x00, 0x00] )

fp = sys.stdout

t0 = time.time()

for i in range ( 10 ):
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

            print ( 
                "%.6f "%dt,
                dye, 
                *["%02x"%r for r in reply2],
                " %.5f "%voltage1,
                led_state,
                file = fp
            )

led.off()
