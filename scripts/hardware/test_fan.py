import RPi.GPIO as GPIO
import time
import sys

# Suppress warnings about GPIO channels already in use
GPIO.setwarnings(False) 

GPIO.setmode(GPIO.BCM) 

FAN_PIN = 17 # Axis
#STEP_PIN = 1

GPIO.setup( FAN_PIN, GPIO.OUT )

state = GPIO.HIGH

if len ( sys.argv ) > 1:
    if sys.argv[1] == "0":
        state = GPIO.LOW

GPIO.output( FAN_PIN, GPIO.LOW)
time.sleep ( 0.1 )

GPIO.output( FAN_PIN, state)
