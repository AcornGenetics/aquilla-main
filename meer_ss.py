from aq_lib.meerstetter import MeerStetter
import time
from serial import Serial


meer1091 = (0x0403, 0x6001, 1089 )
device = MeerStetter.find_meer( * meer1091 )

print ( device )

meer = MeerStetter ( device, timeout = 1 )

meer.setKp(80)     # 40
meer.setTi(5)     # 40
meer.setTd(4)     # 40
meer.setCoarseTempRamp(1.60)     # 40
print ( meer.getKp() )     # 40
print ( meer.getTi() )     # 40
print ( meer.getTd() )     # 40

meer.output_stage_enable ( 1 )

def get_thermocouple( adc ):
    adc.write(b"\r")
    line = adc.readline()
    return float ( line.split(b",")[-2] )

adc = Serial( "/dev/ttyACM0", baudrate=115200 )
t0 = time.time()
for T in (37,89,57):
    meer.set_temperature ( T )
    for i in range (180):
        measured_temp = float ( meer.get_temp()[0] )
        goal_temp = float ( meer.getTargetObjectTemp()[0] )
        tc = get_thermocouple( adc )
        print("%.2f"%(time.time() -t0), "%.3f"%measured_temp, tc, flush = True)
        time.sleep(0.5)

meer.output_stage_enable(0)
