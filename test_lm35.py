

from adc_class import OpticalRead
import time

adc = OpticalRead()
adc.set_channel ( 4,7 )

for i in range ( 10 ):
    reply2 = adc.spi.xfer2( [ 0x42 ] + [0x00,0x00, 0x00] )
    adc_value = adc.convert ( reply2 )
    print ( adc_value )
    time.sleep ( 1 )

