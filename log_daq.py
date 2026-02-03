import time
from serial import Serial

def get_thermocouple( adc ):
    adc.write(b"\r")
    line = adc.readline()
    return line.strip()

adc = Serial( "/dev/ttyACM0", baudrate=115200 )
while True:
    tc = get_thermocouple( adc )
    print("%.2f"%(time.time()), tc.decode(), flush = True)
    time.sleep(0.5)

