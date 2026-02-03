import time
import pprint

from aq_lib.meerstetter import MeerStetter
from aq_lib.config_module import Config

config = Config()

device_type = int (config.pcr["device_type"] )
pid = int(config.pcr["pid"], 16)
vid = int(config.pcr["vid"], 16)
device = MeerStetter.find_meer( vid, pid, device_type)

if device == None:
    raise Exception ( "Couldn't find the device" )
else:
    print ("Found device")


meer = MeerStetter(device, baudrate = 57600, timeout = 1 )

parameters = dict()

for func_name, parid, (getter, setter )  in meer.attributes:

    ret = getter()
    print ( func_name, parid, ret )
    parameters [ parid ] = ( func_name, *ret )

for func_name, parid, (getter, )  in meer.long_attributes:

    ret = getter()
    print ( func_name, parid, ret )
    parameters [ parid ] = ( func_name, *ret )


pprint.pprint ( parameters )
meer.enable( 0,0  )

meer.print_info()

meer.setTi( 10 )
kp = meer.getKp()
ti = meer.getTi()
td = meer.getTd()
print ( "kp Ti Td", kp, ti, td )
kp = meer.get_parid_float( 3010, 1); print ( "kp (parid)", kp )
ti = meer.get_parid_float( 3011, 1); print ( "ti (parid)", ti )
td = meer.get_parid_float( 3012, 1); print ( "td (parid)", td )

kp = meer.get_parid_float( 3010, 2); print ( "kp (parid)", kp )
ti = meer.get_parid_float( 3011, 2); print ( "ti (parid)", ti )
td = meer.get_parid_float( 3012, 2); print ( "td (parid)", td )

T_offset = meer.get_parid_float( 4001, 1); print ( "T_offset (parid)", T_offset )
T_gain = meer.get_parid_float( 4002, 1); print ( "T_gain (parid)", T_gain )

maxV = meer.get_max_voltage ()
print ( f"Max voltage: {maxV}" )
maxV = meer.get_max_current ()
print ( f"Max current: {maxV}" )
