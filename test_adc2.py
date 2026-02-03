import time 
from adc_class import OpticalRead
import RPi.GPIO as GPIO
import time
import sys
from test_positions import goto_position


GPIO.setmode(GPIO.BCM)

pin_22 = 22
pin_27 = 27

GPIO.setup(pin_22, GPIO.OUT)
GPIO.setup(pin_27, GPIO.OUT)

adc = OpticalRead()
adc.set_channel_dye( "FAM" )
reply1 = adc.spi.xfer2( [ 0x41 ] + [0x00,0x00, ] )
print ( "ADC reply to 0x41:" )
print ( reply1 )

try:
    goto_position ( int ( sys.argv[1] ) )
except IndexError as ie:
    print ( "No position argument passed" )
    print ( "Usage:" )
    print ( sys.argv[0] + "<0-6>" )

    exit ( 0 )


GPIO.output( 27, GPIO.LOW )
t0 = time.time()
for i in range ( 200*10):
    dt = time.time() - t0
    time.sleep ( max ( 0, i/60.0-dt ) )
    reply2 = adc.spi.xfer2( [ 0x42 ] + [0x00,0x00, 0x00] )
    if (i%20)>10:
        GPIO.output( pin_27, GPIO.HIGH )
    else:
        GPIO.output( pin_27, GPIO.LOW )

    voltage1 = 1000*adc.convert ( reply2 )

    print ( "%.6f"%dt, end=" " )
    print ( ".".join( [ "%02x"%r for r in reply2] ), end=" " )
    print ( "%7.4f"%voltage1, end = " "   )
    print ( flush=True)

GPIO.output( pin_27, GPIO.LOW )
