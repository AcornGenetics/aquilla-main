# pin_definitions.py
# Mon 13 Oct 08:54:18 PDT 2025

import time
import logging
import RPi.GPIO as GPIO
from RPi.GPIO import HIGH, LOW, IN, OUT, BCM
from aq_lib.config_module import Config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger( "aquila.motor" )

config = Config()


class Motor():

    position = 0

    def __init__( self ):
        self.gpio = GPIO
        self.gpio.setmode(BCM)
        self.gpio.setup( self.EN_PIN  , OUT, initial=HIGH )
        self.gpio.setup( self.STEP_PIN, OUT )
        self.gpio.setup( self.DIR_PIN , OUT )
        logger.info( "Setting pin %d", self.HME_PIN )
        self.gpio.setup( self.HME_PIN , IN )
        logger.info( "Setup motor pins" )

    def move_out_of_home(self):
        return self.move_wo_home_flag( 100, 0.0020 )

    def home( self ):
        steps = self.home_steps
        if self.isHome():
            self.move_out_of_home()

        logger.info("Homing using %d steps", steps)
        ret = self.move_w_home_flag( -steps, 0.0020 )
        if self.isHome():
            self.reset_position()
        else:
            logger.error("Did not reach home.")

        return ret

    def reset_position( self ):
        if abs(self.position) > 20:
            logger.warning("Position Error %d",self.position )
        logger.info("Resetting motor position: %d -> 0", self.position )
        self.position = 0

    def enable( self ):
        self.gpio.output ( self.EN_PIN, LOW )

    def disable( self ):
        self.gpio.output ( self.EN_PIN, HIGH )

    def isHome(self):
        return self.gpio.input ( self.HME_PIN )

    def move_w_home_flag( self, steps, step_delay = 0.0 ):

        logger.info( "Moving with home flag: %d", steps )
        self.set_dir ( steps )
        self.enable()

        steps_traveled = steps
        for i in range( abs( steps ) ):
            if self.gpio.input ( self.HME_PIN ):
                logger.info( "Caught home flag after %d steps", i )
                steps_traveled = i
                break
            for k in range ( self.step_multiplier ):
                self.gpio.output( self.STEP_PIN, HIGH)
                self.gpio.output( self.STEP_PIN, LOW)
                time.sleep ( 0.0001 )

            time.sleep( step_delay )

        if steps > 0:
            self.position += steps_traveled
        else:
            self.position -= steps_traveled

        logger.info("Position after homing: %d", self.position)
        return steps_traveled

    def move_abs_w_home_flag( self, position, step_delay = 0.0 ):
        delta = position - self.position
        return self.move_w_home_flag( delta, step_delay )

    def move_abs_wo_home_flag( self, position, step_delay = 0.0 ):
        logger.info( "Moving %d", position )
        delta = position - self.position
        logger.info( "Moving delta %d", delta )
        return self.move_wo_home_flag( delta, step_delay )

    def set_dir( self, steps ):
        if steps < 0:
            logger.info( "Setting DIR=LOW" )
            self.direction = 1
            self.gpio.output( self.DIR_PIN, self.DIR_BACK_STATE)
        else:
            logger.info( "Setting DIR=HIGH" )
            self.direction = 0
            self.gpio.output( self.DIR_PIN, self.DIR_FORWARD_STATE)

    def move_wo_home_flag( self, steps, step_delay = 0.0 ):

        self.set_dir( steps )
        self.enable()

        for i in range( abs( steps ) ):
            for k in range ( self.step_multiplier ):
                self.gpio.output( self.STEP_PIN, HIGH)
                self.gpio.output( self.STEP_PIN, LOW)
                time.sleep ( 0.0001 )

            time.sleep( step_delay )

        self.position += steps
        logger.info( "Position updated to: %d", self.position )
        return steps

    def test(self ):
        for _ in range ( 1 ):
            logger.info ( "1000 steps forward" )
            #self.move_wo_home_flag (   16000, 0 )
            logger.info ( "1000 steps backwards" )
            self.move_w_home_flag (   -20000, 0 )

class Drawer ( Motor ):

    EN_PIN = 12 
    STEP_PIN = 5
    DIR_PIN = 25
    HME_PIN = 24
    DIR_BACK_STATE = LOW
    DIR_FORWARD_STATE = HIGH
    step_multiplier = config.drawer["step_multiplier"]
    open_steps = config.drawer["open_steps"]
    read_steps = config.drawer["read_steps"]
    home_steps = config.drawer["home_steps"]

    def open( self ):
        self.home()
        ret = self.move_abs_wo_home_flag ( self.open_steps, 0.002 )

    def read( self ):
        self.home()
        ret = self.move_wo_home_flag ( self.read_steps, 0.001 )

class Axis ( Motor ):

    EN_PIN = 26
    STEP_PIN = 19
    DIR_PIN = 13
    HME_PIN = 16
    DIR_BACK_STATE = HIGH
    DIR_FORWARD_STATE = LOW
    step_multiplier = config.axis["step_multiplier"]
    home_steps = config.axis["home_steps"]

    w0 = config.axis["well_one"]
    dw = config.axis["well_spacing"]

    def __init__( self ):
        super().__init__()
        self.positions = [ self.w0 + self.dw*i for i in range(6) ]

    def goto_position( self, N ):
        logger.info( "Go to position: %d", N )
        self.move_abs_wo_home_flag( self.positions[N], 0.001 )

def main():

    import sys

    motor_list = {
                "axis": Axis,
                "drawer": Drawer,
            }

    try:
        motor = sys.argv[1].lower()
        assert motor in motor_list
        steps = int(sys.argv[2] )
        assert "%d"%steps == sys.argv[2]
    except Exception as e:
        print ( e )
        print ( "Usage:", sys.argv[0], "drawer/axis <steps>" )
        exit( -1 )

    MotorClass = motor_list[ motor ]
    motor = MotorClass()
    motor.move_w_home_flag( steps, 0 )

if __name__ == "__main__":
    main()
