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

for led in leds: 
    led.off()
