import logging
import logging.config

from state_run_assay import AssayInterface
from sentri_lib.config_module import Config
from sentri_lib.utils import APP_LOGGING_CONFIG
import sentri_lib.state_requests as sr

logging.config.dictConfig( APP_LOGGING_CONFIG )
logger = logging.getLogger( "aquila_app" )

def main():
    try:
        ai = AssayInterface()
        while True:
            ai.ready()
            ai.run()
            ai.end()
    except Exception as e:
        print("Exception caught in execution of application")
        print ( e )
        sr.change_screen("-1")

if __name__ == "__main__":
    main()
