import RPi.GPIO as GPIO
import time
import logging
import sys

GPIO.setmode(GPIO.BCM)


pin = 8

GPIO.setup(pin, GPIO.OUT)

for i in range ( 100 ):
    GPIO.output(pin, GPIO.HIGH)
    time.sleep ( 0.5 )
    GPIO.output(pin, GPIO.LOW)
    time.sleep ( 0.5 )
