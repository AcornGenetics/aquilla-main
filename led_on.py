import time
import sys
from led_class import LED

if len ( sys.argv ) >= 2:
    if sys.argv[1].lower() == "fam":
        leds = [ LED( "fam" ) ]
    elif sys.argv[1].lower() == "rox":
        leds = [ LED( "rox" ) ]
else:
    leds = [ LED("fam"), LED( "rox" ) ]

try:
    while True:
        for led in leds: 
            led.on()
        time.sleep ( 0.8 )
        for led in leds: 
            led.off()
        time.sleep ( 0.8 )
except KeyboardInterrupt as ke:
    led.off()



