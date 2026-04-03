import json
import os
import socket
from serial.tools import list_ports

class Config():

    def __init__(self):

        self.hostname = os.environ.get("DEVICE_HOSTNAME", socket.gethostname())

        config_dir = os.environ.get("CONFIG_DIR", "config_files")
        config = self.load_config(config_file = os.path.join(config_dir, "host_config.json"))
        state_config = self.load_config(config_file = os.path.join(config_dir, "state_config.json"))
        self.dict = config
        self.state = state_config
        self.__dict__.update ( self.dict )
        

    def load_config( self, config_file):
        with open ( config_file, "r" ) as fp:
            return json.load( fp )

    def find_by_serial_number( self, name ):

        if "serial_number" in self.__dict__[name]:
            serial_number = self.arduino["serial_number"]

            for port in list_ports.comports():
                if ( port.serial_number == serial_number ):
                    #print( "Found serial port" )
                    return port.device

        return None

    def find_by_vid_pid( self, name ):
        device = None
        pid = int ( self.__dict__[name]["pid"], 16 )
        vid = int ( self.__dict__[name]["vid"], 16 )
        for el in list_ports.comports():         
            if ( el.vid, el.pid ) == ( vid, pid ):
                print( el )
                device = el.device
                break

        return device


if __name__ == "__main__":
    config = Config ()
 
