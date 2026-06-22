"""
    hw_api.py

    Interface to mcu rpc.

"""

# pylint: disable=trailing-whitespace, missing-function-docstring

# Built in imports
import os
import time
from datetime import datetime
from enum import Enum
import threading
import logging
import requests
import pdb;#pdb.set_trace()

# 3rd party
from RPi import GPIO
from simple_rpc import Interface

#local imports
from .config_module import Config
from . import pin_definitions as pin_def
from . import workflow_definitions as work_def


config = Config()
logger = logging.getLogger("cart")
main_logger = logging.getLogger("cubit")

class DockInterface():

    def __init__( self ):
        #set up logging
        log_dir = "logs"

        self.t0 = time.time()
        self.t_start = None
        self.t_end = None
        self.run_ID = ""

        #set up mcu
        BAUD = config.arduino["baudrate"]

        if config.arduino["comport"] == config.find_by_serial_number("arduino" ):
            device = config.arduino["comport"]
        else:
            device = config.find_by_vid_pid("arduino")

        if device is None:
            main_logger.critical("Serial port not found for arduino")
            logger.critical("Serial port not found for arduino")
            raise Exception ( "Serial port not found for arduino" )
        
        self.interface = Interface( device = device, baudrate = BAUD)
    
    def start_time( self ):
        self.t_start = time.time()
        logger.info("Start time: %d", self.t_start)
        self.t_end = None
    
    def get_start_time( self ):
        if self.t_start == None:
            return None
        return self.t_start
        

    def end_time( self ):
        self.t_end = time.time()
        if self.get_start_time() != None or self.t_end != None:
            logger.info("Start time: %d", self.get_start_time())
            logger.info("End time: %d", self.t_end)
            logger.info("Duration from time_start: %d", self.t_end - self.get_start_time())
        else:
            logger.info("End time: %d", self.t_end)

    def get_end_time( self ):
        if self.t_end == None:
            return None
        return self.t_end
    
    def generate_runid( self ):
        self.run_ID = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return self.run_ID
    
    def get_run_ID( self ):
        return self.run_ID


    def call_method( self, * args ):
        t0 = time.time()
        logger.debug( "call method: %s", args ) 
        ret = self.interface.call_method( * args )
        logger.debug ( "reply: %s duration: %.2f", ret, time.time() - t0 )
        return ret


    def 

    def fan_on( self ):
        self.interface.call_method( "digitalWrite", 52, int( 1 ))
   
    def fan_off( self ):
        self.interface.call_method( "digitalWrite", 52, int( 0 ))
 
    def home_all_motors( self ):
        pass 

    def open_drwr( self ): 
        pass
    
    def close_drwr( self ):
        pass

    def turn_off_motors(self):
        pass
        
    def digitalWrite(self, pin, state ):
        self.call_method("digitalWrite", pin, state )
    
    def digitalRead(self, pin):
        return self.call_method("digitalRead",pin)


if __name__ == "__main__":
    test = DockInterface()
    test.check_temps()
    
