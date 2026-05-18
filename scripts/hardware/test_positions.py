import logging
import logging.config
import RPi.GPIO as GPIO
import sys

from aq_lib.config_module import Config
from aq_lib.utils import load_json
from aq_lib.utils import LogFileName
from aq_lib.utils import LOGGING_CONFIG

from aq_lib.motor_class import Axis, Drawer
import sys
import time

#logging.config.dictConfig( LOGGING_CONFIG )
#logger = logging.getLogger( "aquila_logger" )
config = Config()

def goto_position( pos_nr ):

    axis = Axis()
    axis.enable()
    ret = axis.move_w_home_flag (   -2200, 0.001 )
    axis.reset_position()
    time.sleep ( 0.5 )
    axis.goto_position ( pos_nr )


    axis.disable()


    #axis.disable()

def main():

    if 0<=int ( sys.argv[1] )<6:
        pos_nr = int ( sys.argv[1] )
        goto_position( pos_nr )
        print ( pos_nr )
    else:
        raise Exception("wrong input")


if __name__ == "__main__":
    main()
