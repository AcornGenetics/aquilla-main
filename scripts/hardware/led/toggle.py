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

try:
    while True:
        # Toggle pin 22
        GPIO.output(pin_22, GPIO.HIGH)  # Turn pin 22 on
        print(f"Pin {pin_22} HIGH")
        time.sleep(5)  # Wait for 1 second
        GPIO.output(pin_22, GPIO.LOW)   # Turn pin 22 off
        print(f"Pin {pin_22} LOW")
        #time.sleep(0.5)  # Wait for 1 second

        # Toggle pin 27
        GPIO.output(pin_27, GPIO.HIGH)  # Turn pin 27 on
        print(f"Pin {pin_27} HIGH")
        time.sleep(5)  # Wait for 1 second
        GPIO.output(pin_27, GPIO.LOW)   # Turn pin 27 off
        print(f"Pin {pin_27} LOW")
        time.sleep(5)  # Wait for 1 second

except KeyboardInterrupt:
    print("Script terminated by user.")

finally:
    # Clean up the GPIO settings to release the pins
    GPIO.cleanup()
    print("GPIO cleanup complete.")
