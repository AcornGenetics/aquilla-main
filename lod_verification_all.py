import sys
from adc_class import OpticalRead
from led_class import LED
import time
from aq_lib.motor_class import Axis, Drawer

dye = sys.argv[1].lower()

drawer = Drawer()
axis = Axis()

drawer.read()
axis.home()

if dye == "fam":
    positions = [2, 3, 4, 5]  # FAM positions (wells A, B, C, D)
elif dye == "rox":
    positions = [0, 1, 2, 3]  # ROX positions (wells A, B, C, D)
else:
    raise Exception("Wrong dye request - use 'fam' or 'rox'")

led = LED(dye)
adc = OpticalRead()
time.sleep(0.1)

adc.set_channel_dye(dye)

for i in range(0):
    time.sleep(0.1)
    reply2 = adc.spi.xfer2([0x42] + [0x00, 0x00, 0x00])

fp = sys.stdout

t0 = time.time()

# Loop through all 4 positions
for position in positions:
    axis.goto_position(position)
    time.sleep(0.2)
    
    for i in range(10):
        for led_state in [1, 0]:
            for k in range(10):
                time.sleep(1.0 / 59.0)
                if led_state:
                    led.on()
                else:
                    led.off()

                dt = time.time() - t0
                reply2 = adc.spi.xfer2([0x42] + [0x00, 0x00, 0x00])
                voltage1 = 1000 * adc.convert(reply2)

                print(
                    "%.6f " % dt,
                    dye,
                    position,  # Added position to output
                    *["%02x" % r for r in reply2],
                    " %.5f " % voltage1,
                    led_state,
                    file=fp
                )

led.off()
drawer.open()
