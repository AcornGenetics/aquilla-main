import RPi.GPIO as GPIO
import time

# Set the numbering mode for the GPIO pins (BCM or BOARD)
# BCM refers to the Broadcom SOC channel number (GPIO numbers)
# BOARD refers to the physical pin numbers on the header
GPIO.setmode(GPIO.BCM)

# Define the GPIO pins you want to toggle
pin_22 = 22
pin_27 = 27

# Set up the pins as output
GPIO.setup(pin_22, GPIO.OUT)
GPIO.setup(pin_27, GPIO.OUT)

# Toggle pin 27
GPIO.output(pin_22, GPIO.HIGH)  # Turn pin 27 on
print(f"Pin {pin_22} HIGH")
time.sleep(5)  # Wait for 1 second
GPIO.output(pin_22, GPIO.LOW)  # Turn pin 27 on
print(f"Pin {pin_22} LOW")
