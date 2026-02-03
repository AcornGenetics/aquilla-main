import os
import json
from .meerstetter import MeerStetter
from .meerstetter import get_time, set_time
from simple_rpc import Interface
import time
from datetime import datetime
import logging
from neb_lib.config_module import Config

logger = logging.getLogger( "aquila" )

config = Config()

T_tolerance = .5

temp_log_dir = "logs"

class RunTec( ):
    def __init__(self):
        self.STC_FAN_GPIO = 53 #dock 2
        self.stop_event = None

    def initialize_meerstetter( self, device_type, thermal_config, run_ID):
        self.output_dir = self.load_json( thermal_config )["output_dir"]
        self.logfilename = self.generate_filename(dock_name,self.output_dir,run_ID)
        self.log_file_path = os.path.join(temp_log_dir, self.logfilename)
        logger.info( "Initializiing meerstetter" )

        self.device = MeerStetter.find_meer( 0x0403, 0x6015, device_type)

        if self.device == None:
            logger.error("Could not find meer")
            raise Exception ( "Couldn't find the device" )
        else:
            print("meet found")
            #logger.info ( "Meerstetter detected at", *self.device )
        
        self.s0 = set_time()
        self.meer = MeerStetter(self.device, baudrate = 57600, timeout = 1 )
        
        time.sleep ( 2 )

        self.steps = self.load_json( thermal_config )["steps"]
        logger.info("STC profile used: %s" % thermal_config)

    def load_json( self, fname ):
        with open ( fname, "r" ) as fp:
            return json.load ( fp )
    

    def thermal_logic(self, interface):

        output_path = os.path.join("logs",self.output_dir, self.logfilename)

        with open ( output_path, "w" ) as logfile:
            print ( f"#Started at {self.s0}", file = logfile )

            0 = get_time()
        
            for args in self.thermocycle ( self.steps ):
                if self.stop_event and self.stop_event.is_set():
                    raise Exception("Forced to exit")

                if args[0] == "cmd":
                    logger.info( "Cmd")
                    cmd = args[1]["cmd"]
                    arg_list = args[1]["args"]
                    fun = getattr( self.meer, cmd )
                    fun ( *arg_list )
                    time.sleep (5)
                    continue

                if args[0] == "pcr_fanon":
                    FANC1 = 52
                    interface.digitalWrite ( FANC1,  True )
                    continue

                if args[0] == "pcr_fanoff":
                    FANC1 = 52
                    interface.digitalWrite ( FANC1,  False )
                    continue

                if args[0] == "call":
                    method_name = args[1]
                    arguments = args[2]
                    fun = getattr(self.meer, method_name )
                    fun( * arguments )
                    continue

                if args[0] == "ramp rate":
                    logger.info( "Ramprate")
                    continue

                name, n, last_temp, setpoint, duration, last_time = args
                if name == "hold":
                    logger.info (f"{n:2} Hold            {setpoint} for {duration:6.2f} seconds until {last_time:.2f}")
                    self.meer.log ( endtime = last_time, logfile = logfile )

                elif name == "ramp":
                    logger.info( f"{n:2} Ramp from {last_temp} to {setpoint} for {duration:6.2f} seconds until {last_time:.2f}")
                    self.meer.change_setpoint ( setpoint )
                    self.meer.log ( endtime = last_time, logfile = logfile )

                elif name == "disable":
                    logger.info( f"{n:2} disable for {duration:6.2f} seconds until {last_time:.2f}")
                    self.meer.output_stage_enable ( 0 )
                    self.meer.log ( endtime = last_time, logfile = logfile )
                    
                elif name == "enable":
                    logger.info( f"{n:2} enable for {duration:6.2f} seconds until {last_time:.2f}")
                    self.meer.output_stage_enable ( 1 )
                    self.meer.log ( endtime = last_time, logfile = logfile )

                else:
                    self.meer.output_stage_enable ( 0 )
                    logger.error ("Unknown command.")
                    break
        return


def main():
    #run_tec(heating_duration = 1)
    return

if __name__ == '__main__':
    main()

