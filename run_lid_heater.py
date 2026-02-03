import aq_lib.regulate
from aq_lib.regulate import lid_heater_worker 
import time

def main():

    # If I reach this point it means I am on my own.
    # Going to import some top level tools. 

    import sys

    from threading import Thread
    from threading import Event
    import logging.config

    sys.path.append ( ".." )
    from aq_lib.utils import LOGGING_CONFIG
    logging.config.dictConfig( LOGGING_CONFIG )

    stop_event = Event()
    quiet_event = Event()
    quiet_event.clear()    
    thread = Thread( target = lid_heater_worker, args=( stop_event, quiet_event,) )
    thread.start()

    try:
        for counter in range ( 60*60 ):
            print ( "Counter: ", counter, flush = True )
            time.sleep ( 1 )
    except KeyboardInterrupt:
        print("Done.")

    print("Turning off heater.")
    stop_event.set()
    thread.join ( timeout = 5 )

if __name__ == "__main__":
    main()
