
import RPi.GPIO as GPIO
import time

# Suppress warnings about GPIO channels already in use
GPIO.setwarnings(False) 

GPIO.setmode(GPIO.BCM) 


HOME_FLAG1 = 24  # was 7
HOME_FLAG2 = 16




# Set up the GPIO pin as an output
GPIO.setup( HOME_FLAG1, GPIO.IN )
GPIO.setup( HOME_FLAG2, GPIO.IN )

while True:
    print ( GPIO.input( HOME_FLAG1 ), GPIO.input ( HOME_FLAG2 ) )



