import RPi.GPIO as GPIO
import time


class Fan():
    FAN_PIN = 17 # Axis
    def __init__( self ):
        # Suppress warnings about GPIO channels already in use
        GPIO.setwarnings(False) 
        GPIO.setmode(GPIO.BCM) 
        GPIO.setup( self.FAN_PIN, GPIO.OUT )

    def set_state( self, on_off ):
        if on_off:
            GPIO.output( self.FAN_PIN, GPIO.HIGH)
        else:
            GPIO.output( self.FAN_PIN, GPIO.LOW)
