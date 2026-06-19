
import sys

sys.path.append ( ".." )

from simple_rpc import Interface



class HardwareController:
    def call_method(self, method_name, *args):
        

          iface = Interface ( "/dev/ttyACM0" )

          try:
               iface.call_method ( method_name, * args )

          except Exception as e:
               print ( e )

          finally: 
               iface.close()


