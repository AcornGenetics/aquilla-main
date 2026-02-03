import RPi.GPIO as GPIO
import time
import logging
import logging.config
from aq_lib.utils import LID_HEATER_LOGGING_CONFIG

from .lid_temperature import ADS1115

GPIO.setmode(GPIO.BCM) 
pin_number = 21 
GPIO.setup(pin_number, GPIO.OUT, initial=GPIO.LOW) 
adc = ADS1115( address = 0x48 )
#pwm = GPIO.PWM( pin_number, 200 )
#pwm.start(0)

logging.config.dictConfig( LID_HEATER_LOGGING_CONFIG )
logger = logging.getLogger( "lid_heater" )

def lid_heater_worker( stop_event, quiet_event, setpoint = 0.34):

    logger.info("Starting lid heater worker")
    adc.start_continuous(channel=0, pga_fs_v=4.096, sps=64)

    while not stop_event.is_set():
        for i in range ( 10 ):
            try:
                v = adc.read_continuous(pga_fs_v=4.096)
                logger.info("lid AIN0: %.4f V", v)
                break
            except Exception as e:
                logger.warning("Hickup in lid heater ADC")
                if i==9:
                    raise e
            time.sleep ( 0.4 )
        if not quiet_event.is_set():
            if 0.2<v<setpoint:
                GPIO.output( pin_number, GPIO.HIGH )
                #pwm.ChangeDutyCycle(50)

        time.sleep(0.90)
        GPIO.output( pin_number, GPIO.LOW )
        time.sleep(0.10)

    logger.info("Turning off lid heater")
    GPIO.output( pin_number, GPIO.LOW )
    logger.info("Lid heater worker exiting")

def main():

    # If I reach this point it means I am on my own.
    # Going to import some top level tools. 

    import sys

    from threading import Thread
    from threading import Event
    import logging.config

    sys.path.append ( ".." )
    from aq_lib.utils import LOGGING_CONFIG
    LOGGING_CONFIG[ 'handlers' ]['file']['filename'] = "../" + LOGGING_CONFIG[ 'handlers' ]['file']['filename']
    logging.config.dictConfig( LOGGING_CONFIG )

    stop_event = Event()
    thread = Thread( target = lid_heater_worker, args=( stop_event,) )
    thread.start()

    try:
        for counter in range ( 20 ):
            print ( "Counter: ", counter, flush = True )
            time.sleep ( 1 )
    except KeyboardInterrupt:
        print("Done.")

    print("Turning off heater.")
    stop_event.set()
    thread.join ( timeout = 5 )
    GPIO.output( pin_number, GPIO.LOW )

if __name__ == "__main__":
    main()
