
import RPi.GPIO as GPIO
from motor_class import Drawer
import sys


drawer = Drawer( GPIO )

drawer.disable()
