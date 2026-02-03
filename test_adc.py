import time 
from adc_class import OpticalRead
from statistics import stdev
import RPi.GPIO as GPIO
import time

GPIO.setmode(GPIO.BCM)

pin_22 = 22
pin_27 = 27

GPIO.setup(pin_22, GPIO.OUT)
GPIO.setup(pin_27, GPIO.OUT)

adc = OpticalRead()
adc.set_channel( 0,1 )
t0 = time.time()
reply1 = adc.spi.xfer2( [ 0x41 ] + [0x00,0x00, ] )

ringbuffer = [0] * 10

try:
    for i in range ( 100000 ):
        GPIO.output( 27, GPIO.HIGH )
        dt = time.time() - t0
        time.sleep ( max ( 0, 0.00+0.04*i-dt ) )
        reply2 = adc.spi.xfer2( [ 0x42 ] + [0x00,0x00, 0x00] )
        dt = time.time() - t0
        time.sleep ( max ( 0, 0.01+0.04*i-dt ) )
        reply2 = adc.spi.xfer2( [ 0x42 ] + [0x00,0x00, 0x00] )
        voltage1 = 1000*adc.convert ( reply2 )

        GPIO.output( 27, GPIO.LOW )
        dt = time.time() - t0
        time.sleep ( max ( 0, 0.02+0.04*i-dt ) )
        reply2 = adc.spi.xfer2( [ 0x42 ] + [0x00,0x00, 0x00] )
        dt = time.time() - t0
        time.sleep ( max ( 0, 0.03+0.04*i-dt ) )
        reply2 = adc.spi.xfer2( [ 0x42 ] + [0x00,0x00, 0x00] )
        voltage2 = 1000*adc.convert ( reply2 )

        print ( "%.5f"%dt, end=" " )
        print ( "%7.4f"%voltage1, end = " "   )
        print ( "%7.4f"%voltage2, end = " "   )
        print ( "%7.4f"%(voltage1 - voltage2), end=" "  )
        #print ( "%7.5f"%stdev( ringbuffer ), end = " " ) 
        print ()

except Eception as e:
    print ( "Caught exception, turning off led" )
    self.gpio.output( LED_PIN1, HIGH)   # Turn pin 22 off
    self.gpio.output( LED_PIN2, HIGH)   # Turn pin 22 off
    raise e
except KeyboardInterrupt as ke:
    print ( "Caught exception, turning off led" )
    self.gpio.output( LED_PIN1, HIGH)   # Turn pin 22 off
    self.gpio.output( LED_PIN2, HIGH)   # Turn pin 22 off
