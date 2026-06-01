import RPi.GPIO as GPIO
import time

# Suppress warnings about GPIO channels already in use
GPIO.setwarnings(False) 

GPIO.setmode(GPIO.BCM) 

#GPIO_PIN = 26 # Axis
#STEP_PIN = 19
#DIR_PIN = 13
#HME_PIN = 16

GPIO_PIN = 12 # DRAWER
STEP_PIN = 5
DIR_PIN = 0
HME_PIN = 7



# Set up the GPIO pin as an output
GPIO.setup( GPIO_PIN, GPIO.OUT )
GPIO.setup( STEP_PIN, GPIO.OUT )
GPIO.setup( DIR_PIN, GPIO.OUT )
GPIO.setup( HME_PIN, GPIO.IN )

GPIO.output( GPIO_PIN, GPIO.LOW)
time.sleep ( 0.1 )

for k in range ( 10 ):

    GPIO.output ( DIR_PIN, 1 )
    for i in range( 500 ):
        GPIO.output( STEP_PIN, GPIO.LOW)
        time.sleep(0.001)
        GPIO.output( STEP_PIN, GPIO.HIGH)
        time.sleep(0.001)
        if ( GPIO.input ( HME_PIN ) ):
            print ( i )
            break

    GPIO.output ( DIR_PIN, 0 )
    for i in range( 4000 ):
        GPIO.output( STEP_PIN, GPIO.LOW)
        GPIO.output( STEP_PIN, GPIO.HIGH)
        

    time.sleep ( 0.1 )

GPIO.output(GPIO_PIN, GPIO.HIGH)
