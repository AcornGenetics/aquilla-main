import adi
import time
import sys

adc = adi.ad7124( uri="spi://dev/spidev0.0" )
    
print("Available channels:", adc.available_channels)

adc.channel['voltage0'].enabled = True
    
while True:
    # Read the voltage from the specified channel.
    # This will return a float value in Volts.
    voltage = adc.channel['voltage0'].voltage()
    
    print(f"Differential Voltage (AIN0 - AIN1): {voltage:.6f} V")
    
    time.sleep(1) # Read every second

