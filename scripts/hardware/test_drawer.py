#!/usr/bin/python3
import sys
import RPi.GPIO as GPIO

from aq_lib.motor_class import Drawer
from aq_lib.config_module import Config

config = Config()
drawer = Drawer( )

if sys.argv[1] == "home":
    ret = drawer.home()
elif sys.argv[1] == "move":
    steps = int ( sys.argv[2] )
    ret = drawer.move_wo_home_flag ( steps , 0.001 )
elif sys.argv[1] == "open":
    ret = drawer.open()
elif sys.argv[1] == "read":
    ret = drawer.home()
    print ( ret ) 
    ret = drawer.move_wo_home_flag ( config.drawer["read_steps"], 0.001 )
    print ( ret )

drawer.disable()  
