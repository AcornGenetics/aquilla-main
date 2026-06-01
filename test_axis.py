#!/usr/bin/python3
import sys
import RPi.GPIO as GPIO
from aq_lib.motor_class import Axis
from aq_lib.config_module import Config

config = Config()

axis = Axis( )

if sys.argv[1] == "home":
    ret = axis.home()
elif sys.argv[1] == "move":
    steps = int ( sys.argv[2] )
    ret = axis.move_wo_home_flag ( steps , 0 )
elif sys.argv[1] == "position":
    pos = int ( sys.argv[2] )
    assert "%d"%pos == sys.argv[2]
    ret = axis.home()
    ret = axis.goto_position ( pos )
    print ( ret )
elif sys.argv[1] == "sliptest":
    repeats = int ( sys.argv[2] )
    for i in range ( repeats ):
        ret = axis.home()
        ret = axis.goto_position ( 5 )
        #ret = axis.goto_position ( 4 )
        ret = axis.home()

axis.disable()  
